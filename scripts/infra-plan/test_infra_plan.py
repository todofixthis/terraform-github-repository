"""Tests for infra_plan.py.

Each test builds a throwaway git repo, so nothing here touches this checkout.
git runs for real; terraform and gh are replaced by FakeTools, because the
script's job is to drive them, not to test them.
"""

import io
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import infra_plan
import pytest

MODULE_PATTERN = r"^(infra/|[^/]+\.tf$)"
PROJECT_PATTERN = r"^infra/"
BOTH_PATTERNS = pytest.mark.parametrize(
    "pattern", [MODULE_PATTERN, PROJECT_PATTERN], ids=["module", "project"]
)
# Pinned per pattern from the original bash implementation, so a plan comment
# posted by either version matches CI. A mismatch on one platform means the
# hash isn't portable.
GOLDEN_HASHES = {
    MODULE_PATTERN: "b69ad3327bdbcd34bd061429df19e5d9999c0f89",
    PROJECT_PATTERN: "2a10bd4297bb11b363727d9c77c879fbcbacf2e3",
}
ZERO_SHA = "0" * 40


@dataclass
class FakeTools:
    """Stands in for terraform and gh, recording what the script asked of them.

    Each field sets up one situation the script must handle, so a test reads
    as the scenario it covers.
    """

    installed: set[str] = field(default_factory=lambda: {"gh", "terraform"})
    init_fails: bool = False
    init_rewrites_lock: bool = False
    plan_output: str = "No changes.\n"
    open_pr: str = ""
    # A newer merged or closed PR for the branch, which an any-state lookup
    # would return but an open-only one must not
    closed_pr: str = ""
    comment_id: str = ""
    pending_run: str = ""
    failed_run: str = ""
    rerun_fails: bool = False
    calls: list[list[str]] = field(default_factory=list)
    posted: list[tuple[str, str]] = field(default_factory=list)

    def run(
        self, args: list[str], input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Answers one terraform or gh invocation the way the real tool would."""
        self.calls.append(args)
        if args[0] == "terraform":
            return self._terraform(args)
        return self._gh(args, input)

    def _terraform(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Plays terraform's init, validate and plan, by subcommand."""
        if "init" in args:
            if self.init_fails:
                return _done(args, 7, stderr="Error: fake init failure\n")
            if self.init_rewrites_lock:
                with open("infra/github/.terraform.lock.hcl", "a") as lock:
                    lock.write("# rewritten by init\n")
            return _done(args)
        if "validate" in args:
            return _done(args, stdout="Success! The configuration is valid.\n")
        return _done(args, stdout=self.plan_output)

    def _gh(
        self, args: list[str], input: str | None
    ) -> subprocess.CompletedProcess[str]:
        """Plays the gh calls the script makes, telling look-alikes apart by flag.

        `--state open` separates the open-PR lookup from any other, and the
        `status` field separates the pending-run lookup from the failed-run one.
        """
        joined = " ".join(args)
        if args[1:3] == ["pr", "list"]:
            return _done(
                args,
                stdout=self.open_pr if "--state open" in joined else self.closed_pr,
            )
        if args[1:3] == ["run", "list"]:
            return _done(
                args, stdout=self.pending_run if "status" in joined else self.failed_run
            )
        if args[1:3] == ["run", "rerun"]:
            return _done(args, 1 if self.rerun_fails else 0)
        if "--method" in args:
            method = args[args.index("--method") + 1]
            self.posted.append((method, input or ""))
            return _done(args)
        if "--paginate" in args:
            return _done(args, stdout=self.comment_id)
        raise AssertionError(f"unexpected gh call: {args}")


def _done(
    args: list[str], code: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, code, stdout, stderr)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit_all(repo: Path) -> str:
    """Commits every change in the fixture repo and returns the new HEAD."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keeps the maintainer's git config (signing, hooks) out of the fixtures."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / "gitconfig").write_text(
        "[user]\n\temail = test@example.com\n\tname = Test\n"
    )


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    """Routes every terraform and gh call through a FakeTools."""
    fake = FakeTools()
    monkeypatch.setattr(infra_plan, "run_tool", fake.run)
    monkeypatch.setattr(
        infra_plan, "tool_available", lambda name: name in fake.installed
    )
    return fake


@pytest.fixture
def make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Builds a fixture repo with a fixed tree and one commit on develop, and cds into it.

    GOLDEN_HASHES are pinned to this exact tree, so changing any infra file
    here means re-deriving them from the bash implementation's history.
    """

    def build(pattern: str) -> Path:
        repo = tmp_path / "repo"
        (repo / "infra/github").mkdir(parents=True)
        (repo / "tests/fx").mkdir(parents=True)
        (repo / ".infra-paths").write_text(pattern + "\n")
        (repo / ".gitignore").write_text(".terraform/\nterraform.tfstate*\n")
        (repo / "main.tf").write_text('resource "x" "y" {}\n')
        (repo / "infra/github/main.tf").write_text('module "m" {}\n')
        (repo / "infra/github/.terraform.lock.hcl").write_text("# lock\n")
        (repo / "tests/fx/broken.tf").write_text('run "t" {}\n')
        _git(repo, "init", "-q", "-b", "develop")
        _commit_all(repo)
        monkeypatch.chdir(repo)
        return repo

    return build


def _main(*argv: str, stdin: str = "") -> int:
    """Runs the script in-process and returns the exit code a real run would have."""
    try:
        return infra_plan.main(list(argv), io.StringIO(stdin))
    except SystemExit as exit_:
        return int(exit_.code or 0)


def _hash() -> str:
    assert _main("hash") == 0
    return infra_plan.infra_hash(infra_plan.read_pattern())


def _state_present(repo: Path) -> None:
    (repo / "infra/github/terraform.tfstate").write_text("{}\n")


def _first_commit(repo: Path) -> str:
    return _git(repo, "rev-list", "--max-parents=0", "HEAD")


# --- hash -------------------------------------------------------------------


@BOTH_PATTERNS
def test_hash_matches_golden_value(make_repo, pattern):
    """Hashes the fixed fixture tree to the value the bash implementation produced."""
    make_repo(pattern)
    assert _hash() == GOLDEN_HASHES[pattern]


def test_hash_counts_root_tf_for_module_pattern(make_repo):
    """Changes the hash when a root .tf file changes under the module repo's pattern."""
    repo = make_repo(MODULE_PATTERN)
    before = _hash()
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    _commit_all(repo)
    assert _hash() != before


def test_hash_ignores_root_tf_for_project_pattern(make_repo):
    """Leaves the hash alone when a root .tf file changes under a project's pattern."""
    repo = make_repo(PROJECT_PATTERN)
    before = _hash()
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    _commit_all(repo)
    assert _hash() == before


@BOTH_PATTERNS
def test_hash_counts_file_moved_out_of_infra(make_repo, pattern):
    """Changes the hash when an infra file moves out of the infra paths."""
    repo = make_repo(pattern)
    before = _hash()
    _git(repo, "mv", "infra/github/main.tf", "moved.txt")
    _commit_all(repo)
    assert _hash() != before


@BOTH_PATTERNS
def test_hash_counts_non_ascii_infra_path(make_repo, pattern):
    """Changes the hash for a new infra file whose path git would otherwise C-quote."""
    repo = make_repo(pattern)
    before = _hash()
    (repo / "infra/github/fü.tf").write_text("x\n")
    _commit_all(repo)
    assert _hash() != before


@BOTH_PATTERNS
def test_hash_ignores_test_fixture(make_repo, pattern):
    """Leaves the hash alone when a .tf file under tests/ changes."""
    repo = make_repo(pattern)
    before = _hash()
    (repo / "tests/fx/broken.tf").write_text('run "u" {}\n')
    _commit_all(repo)
    assert _hash() == before


def test_missing_pattern_file_is_an_error(make_repo):
    """Exits 2 when .infra-paths is missing, rather than matching nothing."""
    repo = make_repo(PROJECT_PATTERN)
    (repo / ".infra-paths").unlink()
    assert _main("hash") == 2


# --- changed ----------------------------------------------------------------


def _changed_status(repo: Path) -> int:
    return _main("changed", _first_commit(repo), "HEAD")


def test_changed_counts_root_tf_for_module_pattern(make_repo):
    """Reports a change when a root .tf file changes under the module repo's pattern."""
    repo = make_repo(MODULE_PATTERN)
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    _commit_all(repo)
    assert _changed_status(repo) == 0


def test_changed_ignores_root_tf_for_project_pattern(make_repo):
    """Reports no change when only a root .tf file changes under a project's pattern."""
    repo = make_repo(PROJECT_PATTERN)
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    _commit_all(repo)
    assert _changed_status(repo) == 1


@BOTH_PATTERNS
def test_changed_counts_file_moved_out_of_infra(make_repo, pattern):
    """Reports a change when an infra file moves out of the infra paths."""
    repo = make_repo(pattern)
    _git(repo, "mv", "infra/github/main.tf", "moved.txt")
    _commit_all(repo)
    assert _changed_status(repo) == 0


@BOTH_PATTERNS
def test_changed_counts_non_ascii_infra_path(make_repo, pattern):
    """Reports a change for a new infra file with a non-ASCII path."""
    repo = make_repo(pattern)
    (repo / "infra/github/fü.tf").write_text("x\n")
    _commit_all(repo)
    assert _changed_status(repo) == 0


@BOTH_PATTERNS
def test_changed_ignores_test_fixture(make_repo, pattern):
    """Reports no change when only a .tf file under tests/ changes."""
    repo = make_repo(pattern)
    (repo / "tests/fx/broken.tf").write_text('run "u" {}\n')
    _commit_all(repo)
    assert _changed_status(repo) == 1


def test_changed_unknown_base_is_an_error(make_repo):
    """Exits 2 for a base commit the repo doesn't have, never "unchanged"."""
    make_repo(PROJECT_PATTERN)
    assert _main("changed", "0123456789abcdef0123456789abcdef01234567", "HEAD") == 2


def test_changed_unexpected_failure_is_an_error(make_repo):
    """Exits 2 or more on an unexpected failure, which CI must never read as "unchanged"."""
    repo = make_repo(PROJECT_PATTERN)
    (repo / ".infra-paths").write_text("(?<!x\n")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    _commit_all(repo)
    assert _changed_status(repo) >= 2


def test_changed_prints_nothing_when_unchanged(make_repo, capsys):
    """Prints nothing when no infra path changed, as the bash version did."""
    repo = make_repo(PROJECT_PATTERN)
    (repo / "README.md").write_text("readme\n")
    _commit_all(repo)
    assert _changed_status(repo) == 1
    assert capsys.readouterr().out == ""


# --- dirty ------------------------------------------------------------------


def test_dirty_clean_tree(make_repo):
    """Reports a freshly committed tree as clean."""
    make_repo(MODULE_PATTERN)
    assert _main("dirty") == 1


@BOTH_PATTERNS
def test_dirty_counts_untracked_infra_file(make_repo, pattern):
    """Counts an untracked infra file as dirty, since the plan would include it."""
    repo = make_repo(pattern)
    (repo / "infra/github/new.tf").write_text("x\n")
    assert _main("dirty") == 0


def test_dirty_counts_root_tf_for_module_pattern(make_repo):
    """Counts an edited root .tf file as dirty under the module repo's pattern."""
    repo = make_repo(MODULE_PATTERN)
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    assert _main("dirty") == 0


def test_dirty_ignores_root_tf_for_project_pattern(make_repo):
    """Ignores an edited root .tf file under a project's pattern."""
    repo = make_repo(PROJECT_PATTERN)
    (repo / "main.tf").write_text('resource "x" "z" {}\n')
    assert _main("dirty") == 1


@BOTH_PATTERNS
def test_dirty_ignores_test_fixture(make_repo, pattern):
    """Ignores a new .tf file under tests/."""
    repo = make_repo(pattern)
    (repo / "tests/fx/new.tf").write_text('run "u" {}\n')
    assert _main("dirty") == 1


@BOTH_PATTERNS
def test_dirty_counts_file_moved_out_of_infra(make_repo, pattern):
    """Counts a staged move out of the infra paths as dirty."""
    repo = make_repo(pattern)
    _git(repo, "mv", "infra/github/main.tf", "moved.txt")
    assert _main("dirty") == 0


@BOTH_PATTERNS
def test_dirty_counts_non_ascii_infra_path(make_repo, pattern):
    """Counts an untracked infra file with a non-ASCII path as dirty."""
    repo = make_repo(pattern)
    (repo / "infra/github/fü.tf").write_text("x\n")
    assert _main("dirty") == 0


# --- plan mode --------------------------------------------------------------


def test_plan_without_terraform_warns_and_passes(make_repo, tools, capsys):
    """Warns and exits 0 when terraform isn't installed, so a push isn't blocked."""
    make_repo(PROJECT_PATTERN)
    tools.installed = {"gh"}
    assert _main() == 0
    assert "terraform not installed" in capsys.readouterr().out


def test_plan_without_state_validates_only(make_repo, tools, capsys):
    """Validates without planning when state isn't available, and posts nothing."""
    make_repo(PROJECT_PATTERN)
    assert _main() == 0
    out = capsys.readouterr().out
    assert "state not available" in out
    assert "configuration is valid" in out
    assert tools.posted == []


def test_plan_init_failure_points_at_the_infra_root(make_repo, tools, capsys):
    """Passes init's exit code through, with a hint naming infra/github, not the repo root."""
    make_repo(PROJECT_PATTERN)
    tools.init_fails = True
    assert _main() == 7
    err = capsys.readouterr().err
    assert "init failed" in err
    assert "terraform -chdir=infra/github init -upgrade" in err
    assert "terraform -chdir=infra/github providers lock" in err


def test_plan_stops_when_init_rewrites_the_lock(make_repo, tools, capsys):
    """Exits 1 without posting when init changes the committed lock file."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.init_rewrites_lock = True
    tools.open_pr = "5"
    assert _main() == 1
    assert "init changed the lock file" in capsys.readouterr().err
    assert tools.posted == []


def test_plan_without_pr_posts_nothing(make_repo, tools, capsys):
    """Plans but posts nothing when the branch has no open PR yet."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    assert _main() == 0
    assert "no PR yet" in capsys.readouterr().out
    assert tools.posted == []


def test_plan_ignores_closed_pr(make_repo, tools, capsys):
    """Posts nothing when the branch's only PR is merged or closed."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.closed_pr = "7"
    assert _main() == 0
    assert "no PR yet" in capsys.readouterr().out
    assert tools.posted == []


def test_plan_posts_new_comment(make_repo, tools):
    """Posts a new comment that starts with the marker and carries the infra hash."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    assert _main() == 0
    [(method, body)] = tools.posted
    text = json.loads(body)["body"]
    assert method == "POST"
    assert text.startswith("<!-- infra-plan -->")
    assert f"<!-- infra-hash: {GOLDEN_HASHES[PROJECT_PATTERN]} -->" in text


def test_plan_updates_existing_comment(make_repo, tools):
    """Edits the existing plan comment rather than stacking a new one."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    tools.comment_id = "99"
    assert _main() == 0
    assert [method for method, _ in tools.posted] == ["PATCH"]


def test_plan_truncates_huge_plan(make_repo, tools):
    """Truncates a plan past GitHub's comment limit, on a UTF-8 boundary, and says so."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    tools.plan_output = "ü" * 40000
    assert _main() == 0
    [(_, body)] = tools.posted
    text = json.loads(body)["body"]
    assert 60000 < len(text.encode()) <= 65536
    assert "Plan truncated" in text


def test_plan_dirty_tree_posts_nothing(make_repo, tools, capsys):
    """Plans but posts nothing when the infra paths have uncommitted changes."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    (repo / "infra/github/new.tf").write_text("x\n")
    assert _main() == 0
    assert "comment not posted" in capsys.readouterr().out
    assert tools.posted == []


def test_plan_reruns_failed_ci(make_repo, tools):
    """Reruns the failed CI run for HEAD after posting, since a comment triggers none."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    tools.failed_run = "42"
    assert _main() == 0
    assert ["gh", "run", "rerun", "--failed", "42"] in tools.calls


def test_plan_survives_failed_rerun(make_repo, tools, capsys):
    """Warns rather than failing when the rerun itself fails, as the plan has posted."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    tools.failed_run = "42"
    tools.rerun_fails = True
    assert _main() == 0
    assert "rerun it by hand" in capsys.readouterr().out


def test_plan_reports_pending_ci(make_repo, tools, capsys):
    """Reports an in-progress run instead of waiting for it or rerunning anything."""
    repo = make_repo(PROJECT_PATTERN)
    _state_present(repo)
    tools.open_pr = "5"
    tools.pending_run = "43"
    tools.failed_run = "42"
    assert _main() == 0
    assert "still in progress" in capsys.readouterr().out
    assert not any(call[1:3] == ["run", "rerun"] for call in tools.calls)


# --- pre-push ---------------------------------------------------------------


def _pre_push(line: str) -> int:
    """Feeds one line of git's ref list to the pre-push subcommand, as git would."""
    return _main("pre-push", "origin", "url", stdin=line + "\n")


@pytest.fixture
def no_terraform(tools: FakeTools) -> FakeTools:
    """Leaves terraform uninstalled, so a plan run shows up as its warning."""
    tools.installed = {"gh"}
    return tools


def test_pre_push_skips_deletion(make_repo, no_terraform, capsys):
    """Skips a branch deletion, which pushes nothing to plan."""
    repo = make_repo(PROJECT_PATTERN)
    head = _git(repo, "rev-parse", "HEAD")
    assert _pre_push(f"(delete) {ZERO_SHA} refs/heads/old {head}") == 0
    assert "terraform not installed" not in capsys.readouterr().out


def test_pre_push_skips_other_branch(make_repo, no_terraform, capsys):
    """Skips a branch that isn't checked out, since the plan speaks for HEAD only."""
    repo = make_repo(PROJECT_PATTERN)
    head = _git(repo, "rev-parse", "HEAD")
    assert _pre_push(f"refs/heads/other {head} refs/heads/other {ZERO_SHA}") == 0
    out = capsys.readouterr().out
    assert "isn't the checked-out branch" in out
    assert "terraform not installed" not in out


def test_pre_push_plans_infra_change(make_repo, no_terraform, capsys):
    """Runs the plan when the pushed commits change the infra paths."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    head = _commit_all(repo)
    assert _pre_push(f"refs/heads/develop {head} refs/heads/develop {first}") == 0
    assert "terraform not installed" in capsys.readouterr().out


def test_pre_push_plans_head_refspec(make_repo, no_terraform, capsys):
    """Runs the plan for `git push origin HEAD`, which sends the literal ref HEAD."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    head = _commit_all(repo)
    assert _pre_push(f"HEAD {head} refs/heads/develop {first}") == 0
    assert "terraform not installed" in capsys.readouterr().out


def test_pre_push_skips_renamed_push(make_repo, no_terraform, capsys):
    """Skips a push to a differently named branch, whose PR the plan would miss."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    head = _commit_all(repo)
    assert _pre_push(f"refs/heads/develop {head} refs/heads/other {first}") == 0
    out = capsys.readouterr().out
    assert "isn't the checked-out branch" in out
    assert "terraform not installed" not in out


def test_pre_push_skips_unrelated_change(make_repo, no_terraform, capsys):
    """Skips the plan when the pushed commits leave the infra paths alone."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("readme\n")
    head = _commit_all(repo)
    assert _pre_push(f"refs/heads/develop {head} refs/heads/develop {first}") == 0
    assert "terraform not installed" not in capsys.readouterr().out


def test_pre_push_new_branch_compares_with_origin_develop(
    make_repo, no_terraform, capsys
):
    """Compares a new branch with origin/develop, where it branched from."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", first)
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    head = _commit_all(repo)
    assert _pre_push(f"refs/heads/feature {head} refs/heads/feature {ZERO_SHA}") == 0
    assert "terraform not installed" in capsys.readouterr().out


def test_pre_push_blocks_without_origin_develop(make_repo, no_terraform, capsys):
    """Blocks a new branch's push when origin/develop is missing, rather than passing."""
    repo = make_repo(PROJECT_PATTERN)
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _git(repo, "rev-parse", "HEAD")
    assert _pre_push(f"refs/heads/feature {head} refs/heads/feature {ZERO_SHA}") >= 2
    assert "fetch and retry" in capsys.readouterr().out


def test_pre_push_blocks_on_plan_failure(make_repo, tools, capsys):
    """Blocks the push when the plan run that follows fails."""
    repo = make_repo(PROJECT_PATTERN)
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "infra/github/main.tf").write_text('module "n" {}\n')
    head = _commit_all(repo)
    tools.init_fails = True
    assert _pre_push(f"refs/heads/develop {head} refs/heads/develop {first}") == 7
