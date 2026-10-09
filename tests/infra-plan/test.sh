#!/usr/bin/env bash
# Fixture tests for scripts/infra-plan and .githooks/pre-push. Each test builds
# a throwaway git repo, so nothing here touches this checkout or the network.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
module_pattern='^(infra/|[^/]+\.tf$)'
project_pattern='^infra/'
# Pinned per pattern; a mismatch on one platform means the hash isn't portable
golden_module_hash=b69ad3327bdbcd34bd061429df19e5d9999c0f89
golden_project_hash=2a10bd4297bb11b363727d9c77c879fbcbacf2e3

# Keep the maintainer's own git config (signing, hooks) out of the fixtures
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

failures=0
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

pass() {
  echo "✅ $1"
}

fail() {
  echo "❌ $1"
  failures=$((failures + 1))
}

check() {
  local name=$1
  shift
  if "$@"; then
    pass "$name"
  else
    fail "$name"
  fi
}

# A PATH with the script's dependencies and nothing else, so a terraform or gh
# on the maintainer's machine can't leak into a test
minimal_bin="$work/bin"
mkdir -p "$minimal_bin"
for tool in bash cat git head mktemp perl rm tail tee tr wc; do
  ln -s "$(command -v "$tool")" "$minimal_bin/$tool"
done

stub_bin="$work/stubs"
mkdir -p "$stub_bin"
cat > "$stub_bin/terraform" <<'STUB'
#!/usr/bin/env bash
case " $* " in
  *" init "*)
    case "${STUB_INIT:-ok}" in
      fail)
        echo "Error: stub init failure" >&2
        exit 7
        ;;
      rewrite-lock)
        echo "# rewritten by init" >> infra/github/.terraform.lock.hcl
        ;;
    esac
    ;;
  *" validate "*)
    echo "Success! The configuration is valid."
    ;;
  *" plan "*)
    if [[ -n "${STUB_PLAN_BYTES:-}" ]]; then
      head -c "$STUB_PLAN_BYTES" /dev/zero | tr '\0' 'x'
    else
      echo "No changes."
    fi
    ;;
esac
STUB
cat > "$stub_bin/gh" <<'STUB'
#!/usr/bin/env bash
log() {
  echo "$*" >> "$STUB_LOG"
}
case "$1 $2" in
  "pr view")
    if [[ -z "${STUB_PR:-}" ]]; then
      exit 1
    fi
    echo "$STUB_PR"
    ;;
  "run list")
    case "$*" in
      *databaseId,status*)
        echo "${STUB_RUN_PENDING:-}"
        ;;
      *)
        echo "${STUB_RUN_FAILED:-}"
        ;;
    esac
    ;;
  "run rerun")
    log "RERUN $4"
    ;;
  *)
    case "$*" in
      *"--method PATCH"*|*"--method POST"*)
        for arg in "$@"; do
          case "$arg" in
            body=*)
              body=${arg#body=}
              ;;
          esac
        done
        log "$3 ${#body}"
        printf '%s' "$body" > "$STUB_LOG.body"
        ;;
      *--paginate*)
        echo "${STUB_COMMENT_ID:-}"
        ;;
    esac
    ;;
esac
STUB
chmod +x "$stub_bin/terraform" "$stub_bin/gh"

# Builds a fixture repo with a fixed tree and one commit, on branch develop
new_repo() {
  local pattern=$1 dir
  dir=$(mktemp -d "$work/repo.XXXXXX")
  (
    cd "$dir"
    git init -q -b develop
    git config user.email test@example.com
    git config user.name Test
    mkdir -p .githooks infra/github scripts tests/fx
    printf '%s\n' "$pattern" > .infra-paths
    printf '.terraform/\nterraform.tfstate*\n' > .gitignore
    printf 'resource "x" "y" {}\n' > main.tf
    printf 'module "m" {}\n' > infra/github/main.tf
    printf '# lock\n' > infra/github/.terraform.lock.hcl
    printf 'run "t" {}\n' > tests/fx/broken.tf
    cp "$repo_root/scripts/infra-plan" scripts/infra-plan
    cp "$repo_root/.githooks/pre-push" .githooks/pre-push
    git add -A
    git commit -q -m fixture
  )
  echo "$dir"
}

commit_all() {
  (cd "$1" && git add -A && git commit -q -m change)
}

infra_plan() {
  local repo=$1
  shift
  (cd "$repo" && scripts/infra-plan "$@")
}

hash_of() {
  infra_plan "$1" hash
}

# Runs `changed` from the fixture's first commit to HEAD; prints the exit code
changed_status() {
  local repo=$1 first
  first=$(cd "$repo" && git rev-list --max-parents=0 HEAD)
  set +e
  infra_plan "$repo" changed "$first" HEAD >/dev/null 2>&1
  echo $?
  set -e
}

dirty_status() {
  set +e
  infra_plan "$1" dirty >/dev/null
  echo $?
  set -e
}

# Runs plan mode with the stubs on PATH; prints combined output, then the exit
# code on the last line
plan_with_stubs() {
  local repo=$1
  set +e
  (cd "$repo" && PATH="$stub_bin:$minimal_bin" STUB_LOG="$repo/.stub-log" scripts/infra-plan 2>&1)
  echo "exit=$?"
  set -e
}

state_present() {
  printf '{}\n' > "$1/infra/github/terraform.tfstate"
}

# --- hash -------------------------------------------------------------------

test_hash_golden_module() {
  [[ "$(hash_of "$(new_repo "$module_pattern")")" == "$golden_module_hash" ]]
}

test_hash_golden_project() {
  [[ "$(hash_of "$(new_repo "$project_pattern")")" == "$golden_project_hash" ]]
}

test_hash_root_tf_module() {
  local repo before
  repo=$(new_repo "$module_pattern")
  before=$(hash_of "$repo")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  commit_all "$repo"
  [[ "$(hash_of "$repo")" != "$before" ]]
}

test_hash_root_tf_project() {
  local repo before
  repo=$(new_repo "$project_pattern")
  before=$(hash_of "$repo")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  commit_all "$repo"
  [[ "$(hash_of "$repo")" == "$before" ]]
}

test_hash_moved_out() {
  local repo before
  repo=$(new_repo "$project_pattern")
  before=$(hash_of "$repo")
  (cd "$repo" && git mv infra/github/main.tf moved.txt)
  commit_all "$repo"
  [[ "$(hash_of "$repo")" != "$before" ]]
}

test_hash_non_ascii() {
  local repo before
  repo=$(new_repo "$project_pattern")
  before=$(hash_of "$repo")
  printf 'x\n' > "$repo/infra/github/fü.tf"
  commit_all "$repo"
  [[ "$(hash_of "$repo")" != "$before" ]]
}

test_hash_ignores_test_fixture() {
  local repo before
  repo=$(new_repo "$module_pattern")
  before=$(hash_of "$repo")
  printf 'run "u" {}\n' > "$repo/tests/fx/broken.tf"
  commit_all "$repo"
  [[ "$(hash_of "$repo")" == "$before" ]]
}

# --- changed ----------------------------------------------------------------

test_changed_root_tf_module() {
  local repo
  repo=$(new_repo "$module_pattern")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  commit_all "$repo"
  [[ "$(changed_status "$repo")" == 0 ]]
}

test_changed_root_tf_project() {
  local repo
  repo=$(new_repo "$project_pattern")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  commit_all "$repo"
  [[ "$(changed_status "$repo")" == 1 ]]
}

test_changed_moved_out() {
  local repo
  repo=$(new_repo "$project_pattern")
  (cd "$repo" && git mv infra/github/main.tf moved.txt)
  commit_all "$repo"
  [[ "$(changed_status "$repo")" == 0 ]]
}

test_changed_non_ascii() {
  local repo
  repo=$(new_repo "$project_pattern")
  printf 'x\n' > "$repo/infra/github/fü.tf"
  commit_all "$repo"
  [[ "$(changed_status "$repo")" == 0 ]]
}

test_changed_ignores_test_fixture() {
  local repo
  repo=$(new_repo "$module_pattern")
  printf 'run "u" {}\n' > "$repo/tests/fx/broken.tf"
  commit_all "$repo"
  [[ "$(changed_status "$repo")" == 1 ]]
}

test_changed_unknown_base() {
  local repo status
  repo=$(new_repo "$project_pattern")
  set +e
  infra_plan "$repo" changed 0123456789abcdef0123456789abcdef01234567 HEAD >/dev/null 2>&1
  status=$?
  set -e
  [[ "$status" -ge 2 ]]
}

# --- dirty ------------------------------------------------------------------

test_dirty_clean() {
  [[ "$(dirty_status "$(new_repo "$module_pattern")")" == 1 ]]
}

test_dirty_untracked_infra() {
  local repo
  repo=$(new_repo "$project_pattern")
  printf 'x\n' > "$repo/infra/github/new.tf"
  [[ "$(dirty_status "$repo")" == 0 ]]
}

test_dirty_root_tf_module() {
  local repo
  repo=$(new_repo "$module_pattern")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  [[ "$(dirty_status "$repo")" == 0 ]]
}

test_dirty_root_tf_project() {
  local repo
  repo=$(new_repo "$project_pattern")
  printf 'resource "x" "z" {}\n' > "$repo/main.tf"
  [[ "$(dirty_status "$repo")" == 1 ]]
}

test_dirty_ignores_test_fixture() {
  local repo
  repo=$(new_repo "$module_pattern")
  printf 'run "u" {}\n' > "$repo/tests/fx/new.tf"
  [[ "$(dirty_status "$repo")" == 1 ]]
}

test_dirty_moved_out() {
  local repo
  repo=$(new_repo "$project_pattern")
  (cd "$repo" && git mv infra/github/main.tf moved.txt)
  [[ "$(dirty_status "$repo")" == 0 ]]
}

test_dirty_non_ascii() {
  local repo
  repo=$(new_repo "$project_pattern")
  printf 'x\n' > "$repo/infra/github/fü.tf"
  [[ "$(dirty_status "$repo")" == 0 ]]
}

# --- plan mode --------------------------------------------------------------

test_plan_without_terraform() {
  local repo output
  repo=$(new_repo "$project_pattern")
  set +e
  output=$(cd "$repo" && PATH="$minimal_bin" scripts/infra-plan 2>&1; echo "exit=$?")
  set -e
  [[ "$output" == *"terraform not installed"* && "$output" == *"exit=0" ]]
}

test_plan_without_state() {
  local output
  output=$(plan_with_stubs "$(new_repo "$project_pattern")")
  [[ "$output" == *"state not available"* && "$output" == *"configuration is valid"* && "$output" == *"exit=0" ]]
}

test_plan_init_failure() {
  local output
  output=$(STUB_INIT=fail plan_with_stubs "$(new_repo "$project_pattern")")
  [[ "$output" == *"init failed"* && "$output" == *"exit=7" ]]
}

test_plan_init_rewrites_lock() {
  local repo output
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  output=$(STUB_INIT=rewrite-lock plan_with_stubs "$repo")
  [[ "$output" == *"init changed the lock file"* && "$output" == *"exit=1" ]]
}

test_plan_no_pr() {
  local repo output
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  output=$(plan_with_stubs "$repo")
  [[ "$output" == *"no PR yet"* && "$output" == *"exit=0" && ! -f "$repo/.stub-log" ]]
}

test_plan_posts_new_comment() {
  local repo output
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  output=$(STUB_PR=5 plan_with_stubs "$repo")
  [[ "$output" == *"exit=0" ]] \
    && [[ "$(cat "$repo/.stub-log")" == POST* ]] \
    && [[ "$(cat "$repo/.stub-log.body")" == *"<!-- infra-hash: $(hash_of "$repo") -->"* ]]
}

test_plan_updates_existing_comment() {
  local repo
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  STUB_PR=5 STUB_COMMENT_ID=99 plan_with_stubs "$repo" >/dev/null
  [[ "$(cat "$repo/.stub-log")" == PATCH* ]]
}

test_plan_truncates_huge_plan() {
  local repo length
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  STUB_PR=5 STUB_PLAN_BYTES=70000 plan_with_stubs "$repo" >/dev/null
  [[ -f "$repo/.stub-log" ]] || return 1
  length=$(cut -d' ' -f2 < "$repo/.stub-log")
  [[ "$length" -gt 60000 && "$length" -le 65536 ]] \
    && [[ "$(cat "$repo/.stub-log.body")" == *"Plan truncated"* ]]
}

test_plan_dirty_skips_comment() {
  local repo output
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  printf 'x\n' > "$repo/infra/github/new.tf"
  output=$(STUB_PR=5 plan_with_stubs "$repo")
  [[ "$output" == *"comment not posted"* && ! -f "$repo/.stub-log" ]]
}

test_plan_reruns_failed_run() {
  local repo
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  STUB_PR=5 STUB_RUN_FAILED=42 plan_with_stubs "$repo" >/dev/null
  [[ "$(cat "$repo/.stub-log")" == *"RERUN 42"* ]]
}

test_plan_reports_pending_run() {
  local repo output
  repo=$(new_repo "$project_pattern")
  state_present "$repo"
  output=$(STUB_PR=5 STUB_RUN_PENDING=43 STUB_RUN_FAILED=42 plan_with_stubs "$repo")
  [[ "$output" == *"still in progress"* && "$(cat "$repo/.stub-log")" != *RERUN* ]]
}

# --- pre-push hook ----------------------------------------------------------

zero=0000000000000000000000000000000000000000

# Feeds one ref line to the fixture's hook with no terraform on PATH, so a plan
# run shows up as the "terraform not installed" warning; prints output and exit
run_hook() {
  local repo=$1 line=$2
  set +e
  (cd "$repo" && printf '%s\n' "$line" | PATH="$minimal_bin" .githooks/pre-push origin url 2>&1)
  echo "exit=$?"
  set -e
}

test_hook_skips_deletion() {
  local repo output
  repo=$(new_repo "$project_pattern")
  output=$(run_hook "$repo" "(delete) $zero refs/heads/old $(cd "$repo" && git rev-parse HEAD)")
  [[ "$output" != *"terraform not installed"* && "$output" == *"exit=0" ]]
}

test_hook_skips_other_branch() {
  local repo head output
  repo=$(new_repo "$project_pattern")
  head=$(cd "$repo" && git rev-parse HEAD)
  output=$(run_hook "$repo" "refs/heads/other $head refs/heads/other $zero")
  [[ "$output" == *"isn't the checked-out branch"* && "$output" != *"terraform not installed"* ]]
}

test_hook_plans_infra_change() {
  local repo first head output
  repo=$(new_repo "$project_pattern")
  first=$(cd "$repo" && git rev-parse HEAD)
  printf 'module "n" {}\n' > "$repo/infra/github/main.tf"
  commit_all "$repo"
  head=$(cd "$repo" && git rev-parse HEAD)
  output=$(run_hook "$repo" "refs/heads/develop $head refs/heads/develop $first")
  [[ "$output" == *"terraform not installed"* && "$output" == *"exit=0" ]]
}

test_hook_skips_unrelated_change() {
  local repo first head output
  repo=$(new_repo "$project_pattern")
  first=$(cd "$repo" && git rev-parse HEAD)
  printf 'readme\n' > "$repo/README.md"
  commit_all "$repo"
  head=$(cd "$repo" && git rev-parse HEAD)
  output=$(run_hook "$repo" "refs/heads/develop $head refs/heads/develop $first")
  [[ "$output" != *"terraform not installed"* && "$output" == *"exit=0" ]]
}

test_hook_new_branch_uses_origin_develop() {
  local repo first head output
  repo=$(new_repo "$project_pattern")
  first=$(cd "$repo" && git rev-parse HEAD)
  (cd "$repo" && git update-ref refs/remotes/origin/develop "$first" && git checkout -q -b feature)
  printf 'module "n" {}\n' > "$repo/infra/github/main.tf"
  commit_all "$repo"
  head=$(cd "$repo" && git rev-parse HEAD)
  output=$(run_hook "$repo" "refs/heads/feature $head refs/heads/feature $zero")
  [[ "$output" == *"terraform not installed"* ]]
}

test_hook_blocks_without_origin_develop() {
  local repo head output
  repo=$(new_repo "$project_pattern")
  (cd "$repo" && git checkout -q -b feature)
  head=$(cd "$repo" && git rev-parse HEAD)
  output=$(run_hook "$repo" "refs/heads/feature $head refs/heads/feature $zero")
  [[ "$output" == *"fetch and retry"* && "$output" != *"exit=0" ]]
}

# ONLY="test_a test_b" runs a subset
for test_name in ${ONLY:-$(declare -F | awk "{print \$3}" | grep "^test_")}; do
  check "$test_name" "$test_name"
done

if [[ "$failures" -gt 0 ]]; then
  echo "❌ $failures test(s) failed"
  exit 1
fi
echo "✅ all tests passed"
