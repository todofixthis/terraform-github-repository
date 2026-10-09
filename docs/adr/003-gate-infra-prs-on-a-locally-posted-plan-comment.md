---
status: Accepted
date: 2026-10-09
scope: [.githooks/, .github/workflows/, .infra-paths, AGENTS.md, scripts/, tests/infra-plan/]
summary: Gate PRs into develop that change infra paths on a plan comment posted by scripts/infra-plan from the maintainer's machine and matched by infra hash, since local state means CI can't plan.
revisit-when: A second maintainer joins. Per-PR local plans become the bottleneck across dependent repos. Repo config moves to remote state with CI-run plans.
---

# 003: Gate infra PRs on a locally posted plan comment

## Context

Infra changes should be reviewed as plans, not only as HCL diffs: a one-line module bump can recreate a ruleset. But state is local to the maintainer's machine, with no backend, so CI has nothing to plan against. Two kinds of author open infra PRs: the maintainer, and agents — Renovate bumping the module or lock, and cloud Claude Code sessions, which post to GitHub as the maintainer. The check has to work for template-generated projects as well as this repo, so it ships as one script.

## Options

### Option 1: Do nothing

**Pros:** No script, hook or CI job.
**Cons:** Infra PRs merge on the HCL diff alone; the plan is first seen at `apply`, after merge.
**Risks:** A module bump that would destroy or replace something is merged before anyone sees it.

### Option 2: Plan comment posted locally, checked by CI (Accepted)

[`scripts/infra-plan`][] plans on the maintainer's machine and posts the plan to the PR with an **infra hash**: a hash of the committed files matching `.infra-paths`. CI's `infra-plan` job ([`ci.yml`][]) passes only when a comment from an `OWNER` or `COLLABORATOR` carries the PR's current infra hash.

**Pros:** Works with local state and the default `GITHUB_TOKEN`; the plan sits on the PR where review happens.
**Cons:** Every infra PR needs a step from the maintainer, including ones they didn't push.
**Risks:** The comment proves a plan was posted for these files, not that a human read it.

### Option 3: Remote state plus OIDC, so CI plans

**Pros:** Plans on every push with no local step.
**Cons:** A cloud backend and an OIDC trust to bootstrap, for a handful of single-maintainer repos.
**Risks:** CI holds credentials that can read and write every repo's settings.

## Decision

Option 2, in three layers:

- **Agents:** [`AGENTS.md`][] tells them to run the script before opening an infra PR and again once it exists, and never to write the plan comment by hand.
- **The maintainer:** the pre-push hook runs the script whenever a push of the checked-out branch changes the infra paths.
- **Backstop:** CI's `infra-plan` job fails the PR until the comment exists.

The guard catches a forgotten plan, not intent. A cloud agent posts as the maintainer, so its comment has the same `author_association`; only the `AGENTS.md` rule stops one forging the marker.

The hash only proves the merged tree was planned because both trunk rulesets set `strict_required_status_checks_policy`, requiring branches to be up to date (the Admin bypass on `trunk-develop` can skip that): bringing a branch up to date with infra changes on `develop` changes its hash and forces a re-plan.

The hash covers the infra paths only, so a PR that also changes docs or tests doesn't need re-planning on every push. It reads the committed tree, so the comment matches exactly what CI checks out. Release PRs into `main` are exempt: infra is applied from `develop` after merge.

`scripts/infra-plan` is canonical here, and each template repo ships a byte-identical copy. Only `.infra-paths` differs between repos, so the path logic has one implementation, which CI and the hook both call.

## Consequences

- Renovate's module and lock PRs stay red until the maintainer runs `gh pr checkout <n>` then `scripts/infra-plan`. So do the maintainer's own new branches: the hook runs before the PR exists, so the script has nowhere to post until it's run again.
- Posting a comment doesn't re-run `pull_request` CI, so the script reruns a failed run for `HEAD` itself and warns when one is still in progress. An `issue_comment` trigger wouldn't help: those runs execute against the default branch, so they can't report `gate` for the PR's head.
- The hook blocks a push on any plan failure (a plan error, an expired token, a lock rewrite), so `--no-verify` is the routine escape, not only a bypass. Pushes that skip the hook still meet the CI backstop.
- The `OWNER`/`COLLABORATOR` filter trusts every collaborator; a second maintainer would change who can satisfy the guard.

[`AGENTS.md`]: ../../AGENTS.md
[`ci.yml`]: ../../.github/workflows/ci.yml
[`scripts/infra-plan`]: ../../scripts/infra-plan
