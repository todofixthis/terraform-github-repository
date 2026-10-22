---
status: Accepted
date: 2026-10-22
scope: [infra/, main.tf, scripts/, variables.tf]
summary: Keep the module to settings stored on the repo, not a person's own preferences such as watching it; each maintainer watches a new repo by hand, not through a local-exec step or a script.
revisit-when: The provider gains a resource for a user's repository subscription.
---

# 005: Keep personal preferences out of the module

## Context

Some GitHub state looks like repo config but belongs to a person: whether they watch a repo, star it, or which notifications they take from it. `todofixthis/terraform-github-repository`, created by its own first apply on 2026-10-02, still had no watchers on 2026-10-22. The module wasn't the cause: many repos created by hand, as recently as September 2026, were unwatched too. Whether a repo is watched is up to each person, and nothing in a new repo's setup reminds them.

The `integrations/github` provider (v6.13.0, the version `~> 6.13` locks to here) has no resource for watching; its schema has no subscription or notification resource at all. GitHub's REST API does: `PUT /repos/{owner}/{repo}/subscription`, which needs a token with the `notifications` scope. The token `gh` holds here lacks it. The module already runs a `local-exec` as whoever applies it ([`terraform_data.push`][]), so a step calling that endpoint would fit.

## Options

### Option 1: Do nothing (Accepted)

The module manages only settings stored on the repo. Watching stays a manual step after the first apply, listed in `README.md` beside adding the repo to Renovate.

**Pros:** An apply changes the repo and nothing else.
**Cons:** One more step to remember per repo.
**Risks:** A forgotten watch means the repo's issues, PRs and releases go unseen until someone looks.

### Option 2: A `local-exec` watch step in the module

A `terraform_data` beside the push step, calling the subscription endpoint through `gh api` once per repo, maybe behind a `watch` input defaulting to `true`.

**Pros:** Nothing to remember.
**Cons:** The repo is watched by whoever applies, not by whoever wants to watch it. Every apply needs `gh` with the `notifications` scope, or the first apply fails partway. The step only writes, so an unwatch in the UI is neither noticed nor restored.
**Risks:** The module starts carrying one person's preferences, and the next (starring, notification levels) has a precedent.

### Option 3: A script that watches every repo

A script under `scripts/` looping the same `gh api` call over every todofixthis repo, run by hand.

**Pros:** Covers existing repos in one run, outside Terraform.
**Cons:** Still a step to remember, now with a script to maintain.
**Risks:** Rewatches repos the maintainer unwatched on purpose.

## Decision

Option 1. A setting belongs in the module only if it's stored on the repo, so an apply means the same thing whoever runs it. A watch is stored on the person. Option 2 would make every dependent's first apply depend on a token scope unrelated to the repo, for a setting it can't keep in place. With one maintainer ([ADR 003][]) the applier is the watcher today, but a second would get watches they never chose. Option 3 saves no remembering over a one-click step and overrides deliberate unwatches.

The same test settles the next case without a new ADR: starring, notification levels, and any other per-user state stay out of the module.

## Consequences

- `README.md` lists watching the new repo as a step after the first apply.
- Each template's README must list the same step beside the Renovate step [ADR 001][] requires; neither template lists that one yet either.

[ADR 001]: 001-share-the-github-repo-standard-as-a-versioned-terraform-module.md
[ADR 003]: 003-gate-infra-prs-on-a-locally-posted-plan-comment.md
[`terraform_data.push`]: ../../main.tf
