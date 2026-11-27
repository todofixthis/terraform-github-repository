---
status: Accepted
date: 2026-11-27
scope: [.githooks/, .github/workflows/, .infra-paths, AGENTS.md, scripts/]
summary: Gate PRs into develop that change this repo's infra paths on a plan comment posted by the infra-plan script from the maintainer's machine and matched by infra hash; the script stays in this repo alone, since generated projects plan by hand without it (cookiecutter-py ADR 025), so no template ships a copy.
revisit-when: A second maintainer joins; this repo's config moves to remote state with CI-run plans; a template ships infra with a CI plan gate.
---

# 007: Gate infra PRs on a plan comment in this repo alone

## Context

[ADR 003][] gates infra PRs on a plan comment the maintainer's machine posts, because state is local and CI has nothing to plan against. It was written for template-generated projects as well as this repo: each template was to ship a byte-identical copy of the script. Neither ever did. One of its revisit conditions was "Per-PR local plans become the bottleneck across dependent repos", and six generated projects are now adopting the module.

[todofixthis/cookiecutter-py ADR 025][cookiecutter-py ADR 025] decided how they adopt it: the template ships the root module, and the maintainer plans by hand before an infra PR merges, with no plan gate in CI. Generated CI runs on `push` alone, so the gate would have meant a `pull_request` trigger in every project, and a local run per project for each module release. cookiecutter-browser-plugin ships no infra yet; its generated CI is push-only too.

This repo's own infra PRs are of two kinds. Changes to the module itself (root `*.tf`) are planned against this repo's own configuration under `infra/github/`. Renovate's provider and lock PRs make up the rest; it opens no module PRs here, since `infra/github/` uses the module through `source = "../.."`.

## Options

### Option 1: Do nothing

ADR 003 stands as written.

**Cons:** It describes template copies that cookiecutter-py has decided not to ship, so a reader plans for a copy step that never comes.

### Option 2: Keep the gate for this repo alone (Accepted)

ADR 003's mechanism, unchanged, for this repo's infra PRs into `develop`. [`scripts/infra-plan/infra_plan.py`][] plans on the maintainer's machine and posts the plan as a PR comment carrying an infra hash, a hash of the committed files matching `.infra-paths`. CI's `infra-plan` job passes only when a comment from an `OWNER` or `COLLABORATOR` carries the PR's current hash. Three layers enforce it: `AGENTS.md` tells agents to run the script and never write the comment by hand, the pre-push hook runs it on the maintainer's pushes, and CI is the backstop. Both trunk rulesets require branches to be up to date, so bringing infra changes in from `develop` changes the hash and forces a re-plan. Release PRs into `main` are exempt, since infra is applied from `develop` after merge.

**Pros:** Works with local state and the default `GITHUB_TOKEN`, and the plan sits on the PR where review happens.
**Cons:** Every infra PR, Renovate's included, needs a step from the maintainer. The script, its tests and its lint step are kept up for this repo alone.
**Risks:** The comment proves a plan was posted for these files, not that anyone read it. A cloud agent posts as the maintainer, with the same `author_association`, so only the `AGENTS.md` rule stops one forging the marker.

### Option 3: Drop the gate here too

Plan by hand before merging, as generated projects do.

**Pros:** One way of working in every repo using the module, and no script to keep.
**Cons:** A module change is first planned against a real repo only after it's tagged, when each dependent plans its bump.
**Risks:** A release that would destroy or replace something reaches every dependent's bump PR before anyone sees its plan, and a published tag can't be moved to take it back.

## Decision

Option 2. A plan here is the last chance to see a module change act on a real repo before it's tagged, and once dependents may have fetched a tag it can't be moved (the `tags-release` ruleset blocks it). Generated projects plan each bump by hand too, but only after the release exists. This repo's plan covers only the paths its own inputs reach (a public repo with no imports), so it catches a destructive change on those paths and not every one. The mocked `terraform test` runs check some others, such as private visibility, and nothing here exercises adoption's imports. Renovate's provider and lock PRs here pay the gate's cost without that benefit, which one maintainer can carry.

## Consequences

- `AGENTS.md` drops the template-copy procedure: copying the script into a template, and the release-note call-outs that existed for the copies.
- [ADR 004][]'s reasons tied to a template copy no longer apply, and its text now marks them so. Its decision, a stdlib-only Python script run by uv, stands on its other reasons, and the script is linted to the same black, ruff and strict mypy standard as the todofixthis Python projects.
- [ADR 001][]'s consequences about template copies are marked as no longer applying; generated projects' module bumps are held for a hand plan under cookiecutter-py ADR 025.
- Renovate's provider and lock PRs stay red until the maintainer runs `gh pr checkout <n>` then the script. So do the maintainer's own new branches, since the hook runs before the PR exists.
- Posting a comment doesn't rerun `pull_request` CI, so the script reruns a failed run for the PR's head itself and warns when one is still in progress.
- The hook blocks a push when a plan fails (without terraform it warns and lets the push through; without state it only validates), so `--no-verify` is the routine escape; a push that skips the hook still meets the CI backstop.
- The `OWNER`/`COLLABORATOR` filter trusts every collaborator, so a second maintainer would change who can satisfy the gate.

[ADR 001]: 001-share-the-github-repo-standard-as-a-versioned-terraform-module.md
[ADR 003]: 003-gate-infra-prs-on-a-locally-posted-plan-comment.md
[ADR 004]: 004-write-the-infra-plan-script-in-python-run-by-uv.md
[cookiecutter-py ADR 025]: https://github.com/todofixthis/cookiecutter-py/blob/develop/docs/adr/025-ship-github-settings-as-terraform-planned-by-hand.md
[`scripts/infra-plan/infra_plan.py`]: ../../scripts/infra-plan/infra_plan.py
