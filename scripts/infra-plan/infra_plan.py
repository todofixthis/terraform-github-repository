#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Plans this repo's infra changes and posts the plan to the branch's PR.

State is local to the maintainer's machine, so CI can't plan. This script
plans there and posts the plan as a PR comment keyed by the infra hash, and
CI's infra-plan job passes only when that comment matches the PR's committed
infra files (docs/adr/003).

Canonical copy: todofixthis/terraform-github-repository. Template repos ship
it byte-identical at the tag they pin; only .infra-paths differs between
repos. Standard library only, so it needs nothing beyond `uv run --script`.

Usage:
    infra_plan.py                     plan, then post to the PR
    infra_plan.py hash                print the infra hash
    infra_plan.py changed BASE HEAD   exit 0 if the infra paths changed since
                                      merge-base(BASE, HEAD), 1 if not, 2 on
                                      error
    infra_plan.py dirty               exit 0 if the infra paths have
                                      uncommitted or untracked changes, 1 if
                                      not, 2 on error
    infra_plan.py pre-push REMOTE URL the pre-push hook; reads git's ref list
                                      on stdin. git passes REMOTE and URL,
                                      which are ignored: a new branch is
                                      always compared with origin/develop
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

INFRA_DIR = "infra/github"
LOCK_FILE = f"{INFRA_DIR}/.terraform.lock.hcl"
STATE_FILE = f"{INFRA_DIR}/terraform.tfstate"
MARKER = "<!-- infra-plan -->"
# GitHub rejects comment bodies over 65,536 characters
MAX_PLAN_BYTES = 60000
ZERO_SHA_PATTERN = re.compile(r"^0+$")
LOCK_PLATFORMS = ("darwin_amd64", "darwin_arm64", "linux_amd64", "linux_arm64")


class ScriptError(Exception):
    """A failure the caller must treat as an error, never as "unchanged".

    Carries the exit code. Errors from `changed` and `dirty` must use 2 or
    more, since CI and the hook read their 0 and 1 as answers; plan-mode
    errors may use any non-zero code, such as init's own.
    """

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def run_tool(
    args: list[str], input: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Runs terraform or gh, the two tools this script drives but doesn't own.

    Kept as one seam, alongside tool_available, that the tests replace, so
    they can play any tool response without a network or a real Terraform
    state.
    """
    return subprocess.run(
        args,
        input=input,
        stdin=None if input is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def tool_available(name: str) -> bool:
    """Reports whether a tool is on PATH, so a missing one warns rather than crashes."""
    return shutil.which(name) is not None


def git(*args: str) -> bytes:
    """Runs git and returns raw stdout.

    Bytes, not text, so a path elsewhere in the repo that isn't valid
    UTF-8 can't break a listing; one inside the infra paths fails closed
    (exit 2). Listings use -z, which keeps git from C-quoting non-ASCII
    paths whatever core.quotePath says.
    """
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, stdin=subprocess.DEVNULL
    ).stdout


def git_ok(*args: str) -> bool:
    """Runs git for its exit status alone, for checks like "is this a commit?"."""
    result = subprocess.run(
        ["git", *args], capture_output=True, stdin=subprocess.DEVNULL, check=False
    )
    return result.returncode == 0


def current_branch() -> str:
    """Names the checked-out branch, or returns "" on a detached HEAD.

    Plans speak for HEAD and post to its branch's PR, so both plan mode and
    the pre-push check need to know which branch that is.
    """
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def read_pattern() -> re.Pattern[bytes]:
    """Loads the infra path regex from .infra-paths.

    The regex is the one thing that differs between repos sharing this
    script, so it lives in a file of its own rather than in the code.
    """
    path = Path(".infra-paths")
    if not path.is_file() or not path.read_text().strip():
        raise ScriptError("❌ .infra-paths is missing or empty")
    return re.compile(path.read_text().splitlines()[0].encode())


def nul_records(output: bytes) -> list[bytes]:
    """Splits git's NUL-separated output into records, dropping the trailing empty one."""
    return [record for record in output.split(b"\0") if record]


def infra_hash(pattern: re.Pattern[bytes]) -> str:
    """Hashes the committed infra files at HEAD.

    CI matches plan comments by this hash, so it reads the committed tree
    only: a comment posted for HEAD then matches exactly what CI checks out.
    The record format and trailing NULs reproduce the original bash
    implementation, so comments posted by either version match.
    """
    records = [
        record
        for record in nul_records(git("ls-tree", "-r", "-z", "HEAD"))
        if pattern.search(record.split(b"\t", 1)[1])
    ]
    tree_listing = b"".join(record + b"\0" for record in records)
    return (
        subprocess.run(
            ["git", "hash-object", "--stdin"],
            input=tree_listing,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )


def changed_paths(base: str, head: str, pattern: re.Pattern[bytes]) -> list[str]:
    """Lists infra paths changed between merge-base(base, head) and head.

    Diffing from the merge-base means a stale base only adds paths, so it
    can trigger an extra plan but never hide a change. --no-renames lists a
    file moved out of the infra paths under its old path too.
    """
    for label, ref in (("base", base), ("head", head)):
        if not git_ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            hint = " (fetch first?)" if label == "base" else ""
            raise ScriptError(f"❌ unknown {label}: {ref}{hint}")
    try:
        merge_base = git("merge-base", base, head).decode().strip()
    except subprocess.CalledProcessError as error:
        raise ScriptError(f"❌ no merge-base between {base} and {head}") from error
    listing = git("diff", "-z", "--name-only", "--no-renames", merge_base, head)
    return [path.decode() for path in nul_records(listing) if pattern.search(path)]


def dirty_paths(pattern: re.Pattern[bytes]) -> list[str]:
    """Lists infra paths with uncommitted or untracked changes.

    A plan of a dirty tree doesn't describe the committed tree the hash
    covers, so plan mode won't post one.
    """
    listing = git(
        "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"
    )
    # Each porcelain entry is a two-character status, a space, then the path
    paths = [entry[3:] for entry in nul_records(listing)]
    return [path.decode() for path in paths if pattern.search(path)]


def lock_digest() -> str:
    """Fingerprints the provider lock file, so plan mode can tell if init rewrote it."""
    if not Path(LOCK_FILE).is_file():
        return "absent"
    return git("hash-object", LOCK_FILE).decode().strip()


def terraform(*args: str) -> subprocess.CompletedProcess[str]:
    """Runs terraform against the infra root without prompting or colour codes."""
    return run_tool(["terraform", f"-chdir={INFRA_DIR}", *args, "-no-color"])


def run_init(*extra: str) -> None:
    """Initialises the infra root, explaining the usual fix when that fails.

    The hint names the infra root because this script runs from the repo
    root, where a bare `terraform init -upgrade` would upgrade the wrong lock.
    """
    result = terraform("init", "-input=false", *extra)
    if result.returncode == 0:
        return
    sys.stderr.write(result.stdout + result.stderr)
    platforms = " ".join(f"-platform={platform}" for platform in LOCK_PLATFORMS)
    raise ScriptError(
        "⚠️ init failed; on a module or provider bump, run "
        f"`terraform -chdir={INFRA_DIR} init -upgrade` then "
        f"`terraform -chdir={INFRA_DIR} providers lock {platforms}`, and commit the lock",
        result.returncode,
    )


def check_lock(digest_before: str) -> None:
    """Stops when init rewrote the committed lock, which would leave the infra paths dirty."""
    if lock_digest() != digest_before:
        raise ScriptError("⚠️ init changed the lock file; commit it and re-run", 1)


def rerun_failed_ci() -> None:
    """Reruns HEAD's failed CI after posting, since posting a comment triggers no run.

    This does its work when the script is run by hand on a PR that already
    has a failed run, such as a Renovate or cloud-agent PR. From pre-push it
    usually finds nothing, since the push it guards hasn't created a run for
    HEAD yet. It never waits for an in-progress run, so a hook never stalls.
    """
    sha = git("rev-parse", "HEAD").decode().strip()
    pending = run_tool(
        [
            "gh",
            "run",
            "list",
            "--commit",
            sha,
            "--event",
            "pull_request",
            "--json",
            "databaseId,status",
            "--jq",
            '[.[] | select(.status != "completed")][0].databaseId // empty',
        ]
    ).stdout.strip()
    if pending:
        print(
            f"⚠️ CI run still in progress; if it fails, rerun with `gh run rerun --failed {pending}`"
        )
        return
    failed = run_tool(
        [
            "gh",
            "run",
            "list",
            "--commit",
            sha,
            "--event",
            "pull_request",
            "--json",
            "databaseId,conclusion",
            "--jq",
            '[.[] | select(.conclusion == "failure")][0].databaseId // empty',
        ]
    ).stdout.strip()
    if not failed:
        return
    if run_tool(["gh", "run", "rerun", "--failed", failed]).returncode == 0:
        print(f"✅ reran failed jobs in run {failed}")
    else:
        print(f"⚠️ couldn't rerun run {failed}; rerun it by hand")


def comment_body(plan: str, hash_value: str) -> str:
    """Builds the plan comment: the marker first, then the hash CI matches, then the plan.

    The marker must open the body, since later runs find the comment to
    update by it. The plan is cut on a UTF-8 boundary to stay under GitHub's
    comment limit.
    """
    encoded = plan.encode()
    shown = encoded[:MAX_PLAN_BYTES].decode(errors="ignore")
    body = (
        f"{MARKER}\n<!-- infra-hash: {hash_value} -->\n### Terraform plan\n\n"
        f"Infra hash `{hash_value}`.\n\n<details><summary>Plan</summary>\n\n```\n"
        f"{shown}\n```\n\n</details>\n"
    )
    if len(encoded) > MAX_PLAN_BYTES:
        body += (
            "\nPlan truncated; run the infra-plan script locally for the full output.\n"
        )
    return body


def post_comment(plan: str, pattern: re.Pattern[bytes]) -> None:
    """Creates or updates the branch's open PR's plan comment, then reruns failed CI.

    Only an open PR counts: a reused branch name could otherwise land the
    plan on an earlier merged PR while the new one stays red.
    """
    if not tool_available("gh"):
        print("⚠️ gh not installed; comment not posted")
        return
    branch = current_branch()
    if not branch:
        print("⏭️ detached HEAD; comment not posted")
        return
    pr = run_tool(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
            "--jq",
            ".[0].number // empty",
        ]
    ).stdout.strip()
    if not pr:
        print("⏭️ no PR yet; re-run once one exists")
        return
    payload = json.dumps({"body": comment_body(plan, infra_hash(pattern))})
    comment_ids = run_tool(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{{owner}}/{{repo}}/issues/{pr}/comments",
            "--jq",
            f'.[] | select(.body | startswith("{MARKER}")) | .id',
        ]
    ).stdout.split()
    if comment_ids:
        endpoint = f"repos/{{owner}}/{{repo}}/issues/comments/{comment_ids[-1]}"
        result = run_tool(
            ["gh", "api", "--method", "PATCH", endpoint, "--input", "-"], input=payload
        )
    else:
        endpoint = f"repos/{{owner}}/{{repo}}/issues/{pr}/comments"
        result = run_tool(
            ["gh", "api", "--method", "POST", endpoint, "--input", "-"], input=payload
        )
    if result.returncode != 0:
        raise ScriptError(
            f"❌ couldn't post the plan to PR #{pr}: {result.stderr.strip()}", 1
        )
    print(f"✅ plan posted to PR #{pr}")
    rerun_failed_ci()


def plan_mode(pattern: re.Pattern[bytes]) -> int:
    """Plans the infra root and posts the plan, or explains why it can't.

    Handles each situation ADR 003's guard can meet: no terraform (warn and
    pass, so a push isn't blocked), no state (validate only), a failed init,
    init rewriting the lock, and a dirty tree (plan in full but don't post,
    since the plan wouldn't match the committed hash).
    """
    if not tool_available("terraform"):
        print("⚠️ terraform not installed; cannot plan")
        return 0
    is_dirty = bool(dirty_paths(pattern))
    digest_before = lock_digest()
    if not Path(STATE_FILE).is_file():
        print("⚠️ state not available; plan must run on the maintainer's machine")
        run_init("-backend=false")
        check_lock(digest_before)
        result = terraform("validate")
        print(result.stdout + result.stderr, end="")
        return result.returncode
    run_init()
    check_lock(digest_before)
    result = terraform("plan", "-input=false")
    print(result.stdout, end="")
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    if is_dirty:
        print("⚠️ infra paths are dirty; comment not posted")
    else:
        post_comment(result.stdout, pattern)
    return 0


def pre_push(stdin: TextIO, pattern: re.Pattern[bytes]) -> int:
    """Runs plan mode when a push of the checked-out branch changes the infra paths.

    The plan speaks for HEAD and posts to the current branch's PR, so a ref
    counts only when it pushes HEAD's commit to the same-named branch.
    Matching on the SHA and remote ref, not the local ref, covers
    `git push origin HEAD`, which sends the literal ref "HEAD".
    """
    branch = current_branch()
    head_sha = git("rev-parse", "HEAD").decode().strip()
    needs_plan = False
    for line in stdin.read().splitlines():
        if not line.strip():
            continue
        local_ref, local_sha, remote_ref, remote_sha = line.split()
        # Deleting a branch pushes no commits to plan
        if ZERO_SHA_PATTERN.match(local_sha):
            continue
        if local_sha != head_sha or remote_ref != f"refs/heads/{branch}":
            print(
                f"⏭️ {local_ref} -> {remote_ref} isn't the checked-out branch; skipping its infra plan"
            )
            continue
        # A new branch has no remote SHA; compare against where it branched from
        base = "origin/develop" if ZERO_SHA_PATTERN.match(remote_sha) else remote_sha
        try:
            if changed_paths(base, local_sha, pattern):
                needs_plan = True
        except ScriptError as error:
            print(error)
            print(
                f"❌ couldn't tell whether {local_ref} changes the infra paths (exit {error.code}); fetch and retry"
            )
            return error.code
    return plan_mode(pattern) if needs_plan else 0


def print_paths(paths: list[str]) -> None:
    """Lists matched paths for a person reading the output, and prints nothing for none."""
    for path in paths:
        print(path)


def main(argv: Sequence[str], stdin: TextIO) -> int:
    """Dispatches a subcommand from the repo root and turns errors into exit codes.

    An unexpected exception exits 2, never Python's default 1: callers of
    `changed` and `dirty` read 1 as "unchanged", so a broken script would
    otherwise wave infra changes through CI. Expected failures keep the code
    their ScriptError carries.
    """
    command, *args = argv or [""]
    try:
        os.chdir(git("rev-parse", "--show-toplevel").decode().strip())
        pattern = read_pattern()
        if command == "":
            return plan_mode(pattern)
        if command == "hash":
            print(infra_hash(pattern))
            return 0
        if command == "changed" and len(args) == 2:
            paths = changed_paths(args[0], args[1], pattern)
            print_paths(paths)
            return 0 if paths else 1
        if command == "dirty":
            paths = dirty_paths(pattern)
            print_paths(paths)
            return 0 if paths else 1
        if command == "pre-push":
            return pre_push(stdin, pattern)
    except ScriptError as error:
        print(error, file=sys.stderr)
        return error.code
    except Exception as error:
        print(f"❌ {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(
        "usage: infra_plan.py [hash | changed BASE HEAD | dirty | pre-push REMOTE URL]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin))
