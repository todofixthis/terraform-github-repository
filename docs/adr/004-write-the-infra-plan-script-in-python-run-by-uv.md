---
status: Accepted
date: 2026-10-13
scope: [.githooks/, .github/workflows/, .infra-paths, scripts/]
summary: Write the infra-plan script and its pre-push logic as one stdlib-only Python file with PEP 723 metadata, run by uv run --script and tested with pytest, not bash; stdlib-only keeps the byte-identical template copy needing nothing beyond uv.
revisit-when: The script needs a third-party dependency. A repo or environment that runs the script routinely lacks uv.
---

# 004: Write the infra-plan script in Python run by uv

## Context

[ADR 003][]'s plan-comment guard is one script, `scripts/infra-plan`, designed to be copied byte-for-byte into `todofixthis/cookiecutter-py` and `todofixthis/cookiecutter-browser-plugin`, and from there into every generated project; neither template ships it yet. It was written in bash, with Perl one-liners for NUL-separated path filtering, and had to run under macOS's bash 3.2. Its fixture tests grew their own harness (a `check` runner, stub `gh` and `terraform` binaries, a minimal `PATH`) of a size the maintainer flagged in PR review: the tests carry enough custom logic to need tests of their own. Every Python todofixthis project is managed by uv.

## Options

### Option 1: Do nothing

Keep bash, Perl and the hand-rolled test harness.

**Pros:** No new runtime; `bash`, `git` and `perl` are on every Mac and CI runner already.
**Cons:** Every change has to respect bash 3.2 (no `mapfile`, and an empty array errors under `set -u`), and the harness itself is untested.
**Risks:** A harness bug, such as a test whose two sides both come back empty, passes green while checking nothing.

### Option 2: One stdlib-only Python file run by `uv run --script` (Accepted)

The script and the pre-push hook's logic move to `scripts/infra-plan/infra_plan.py`, with PEP 723 inline metadata (Python 3.10 or later, no dependencies), tested with pytest beside it. The hook becomes a short call into it.

**Pros:** pytest's fixtures replace the hand-rolled harness; `tmp_path` and `monkeypatch` cover throwaway repos and the fake `gh`/`terraform` boundary.
**Cons:** uv becomes a requirement wherever the script runs: the maintainer's machine, each CI job that calls it, and generated browser-plugin projects, which otherwise use pnpm.
**Risks:** Python exits 1 on an uncaught exception, and 1 is `changed`'s and `dirty`'s "unchanged" answer, so an unhandled failure would fail open in CI. `main` turns every exception raised once the script is running into exit 2, and a test covers it; a file that fails to compile still exits 1, which this repo's pytest run guards against, as will the byte-identical check each template is to carry.

### Option 3: Keep bash, test with bats-core

**Pros:** A standard shell test framework in place of the custom harness.
**Cons:** Leaves bash 3.2 and Perl in place, and adds a test dependency no other todofixthis project uses.
**Risks:** Same as Option 1 for the script itself.

## Decision

Option 2. The NUL-separated path handling that needed Perl is native in Python (`bytes.split(b"\0")`, `re`), so the script drops a language as well as the bash 3.2 constraint. Keeping it stdlib-only and single-file preserves the byte-identical copy into the templates: there's no lock file or package to ship alongside it, and `uv run --script` needs nothing installed beyond uv. uv is already the toolchain on the maintainer's machine and in every Python todofixthis project, so the new requirement lands mainly on browser-plugin projects.

The hook warns and passes when uv is missing, as the script does when terraform is: CI's guard still holds the PR, so a machine without uv loses only the early warning, not the gate. With uv installed but no usable Python 3.10 or later, cached or on the system, and no network to fetch one, the hook fails and blocks the push; `git push --no-verify` gets past it.

## Consequences

- The canonical copy moves to `scripts/infra-plan/infra_plan.py`. The infra hash, plan-comment markers and exit-code contract (0 changed or dirty, 1 not, 2 or more on error) are unchanged, so a plan comment posted by the old script still satisfies CI. `changed` and `dirty` gained no new outputs, but `pre-push` is a new subcommand, and `.infra-paths` is now read as a Python `re` pattern rather than a Perl one; both patterns in use behave the same under either.
- A template that first ships the script needs more than the copy:
  - where the template renders `{{ }}` (cookiecutter-browser-plugin, under cookiecutter), `_copy_without_render` must cover the file, since it contains literal `{{owner}}`-style placeholders; cookiecutter-py's copier renders only `.jinja` files, so it needs nothing there;
  - a pre-push hook calling it;
  - CI with `setup-uv` running it;
  - a byte-identical check against this repo's copy. The tests stay here and don't ship.
- A template's own hooks may reformat a copy committed there, and generated projects would lint it. The script must stay clean under black, ruff and strict mypy, or a reformatted copy would break the byte-identical check, so this repo's CI runs the same three checks on it.
- Generated browser-plugin projects need uv on the maintainer's machine, alongside pnpm.
- The direct-run shebang (`#!/usr/bin/env -S uv run --quiet --script`) needs `env -S`, which macOS and GNU coreutils have and busybox doesn't. CI and the hook call `uv run --script` explicitly, so only hand and agent runs depend on it.
- CI installs pytest, black, ruff and mypy unpinned through `uv`. No lock file means Renovate can't see them, so a new major arrives unannounced; a new black style could make this CI and a template's hook disagree on the same file.

[ADR 003]: 003-gate-infra-prs-on-a-locally-posted-plan-comment.md
