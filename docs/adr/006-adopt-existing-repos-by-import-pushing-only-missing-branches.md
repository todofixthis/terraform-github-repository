---
status: Accepted
date: 2026-11-17
scope: [README.md, main.tf]
summary: Bring an existing repo under the module with import blocks in its root module, importing its hand-made branch and tag rulesets under the module's ruleset addresses, while the push step pushes only the trunk branches the remote lacks; not an input that skips the push, and not deleting the hand-made rulesets first.
revisit-when: An adoption's plan shows an imported ruleset replaced rather than updated in place.
---

# 006: Adopt existing repos by import, pushing only missing branches

## Context

[ADR 001][] has every todofixthis repo provisioned through this module, but the module was written for repos it creates. Every repo in the rollout already exists, and most already have rulesets made by hand: class-registry and filters-iso have one per trunk branch, named `develop` and `main`; paddock has one covering both; phx-claude-siat's already carry the module's names. Some repos have only `main`.

Two parts of the module meet an existing repo badly:

- **The push step.** [`terraform_data.push`][] runs `git push --no-verify origin develop main` from the local checkout. An adoption's first apply creates it and runs the push, before the rulesets are applied. Importing it doesn't help: its `triggers_replace` isn't in imported state, so the plan replaces it at once and the push runs anyway. A checkout behind its remote fails the apply partway; a local `main` with unpushed commits sends them to `main` unreviewed.
- **The rulesets.** The module creates `trunk-develop`, `trunk-main` and `tags-release`. Beside a repo's hand-made rulesets, both sets apply until someone deletes the old ones.

The provider can import each resource the module declares: rulesets by `<repo>:<ruleset id>`, the rest by repo name. It marks no ruleset attribute `ForceNew`, so a ruleset imported under a module address with a different name, conditions or rules plans as an update in place. The provider's own documentation and its v6.13.0 source (`resourceGithubRepositoryRulesetImport`) agree on this. No repo has been adopted yet: this one was created by its own first apply ([ADR 005][]).

## Options

### Option 1: Do nothing

Adoption stays undocumented, each maintainer working it out per repo.

**Pros:** No module change.
**Cons:** Every adoption has to know to sync the local trunk branches first, and to delete or import the hand-made rulesets.
**Risks:** One adoption from a stale or diverged checkout pushes straight to `main`, which the module exists to prevent.

### Option 2: Push only the branches the remote lacks, and import the rest (Accepted)

The push step checks each trunk branch with `git ls-remote` and pushes only those the remote doesn't have, failing the apply if the check itself fails. The adopting repo's root module carries `import` blocks for the repo and its settings, and imports each hand-made ruleset under the module address it most resembles.

**Cons:** The `import` blocks are hand-written per repo, needing each ruleset's ID.
**Risks:** A remote missing a trunk branch gets the local one, so a stale local `develop` becomes the remote's `develop` for a `main`-only repo.

### Option 3: An input that skips the push

A boolean input, defaulting to pushing, that an adopting root module sets to skip the step, with `count` on the push and a `moved` block for existing state.

**Pros:** Adoption is explicit in the root module.
**Cons:** A `main`-only repo still needs `develop` created by hand before its rulesets apply. Every root module carries a flag that matters for one apply.
**Risks:** A forgotten flag runs the unguarded push Option 1 has.

## Decision

Option 2. It removes the hazard rather than adding a switch to avoid it: the push step is safe whether the repo is new, adopted with both branches, or adopted with only `main`, so no adoption depends on a flag being set. Option 3 guards only the adoptions that remember it.

For the rulesets, importing under the module's addresses beats deleting the hand-made ones and letting the module create its own: the same apply that brings a ruleset under management rewrites it, so a trunk branch already protected stays protected throughout, and the plan comment shows each import beside the changes it makes. Where one hand-made ruleset covers both trunk branches, as paddock's does, it is imported as `trunk-develop` and the module creates `trunk-main`, leaving `main` unprotected for the seconds between the two.

## Consequences

- `README.md` documents adoption: syncing the local trunk branches, finding each ruleset's ID, and writing the `import` blocks.
- An adopted repo's root module drops its `import` blocks once applied. Kept, they would make the module's resource addresses an interface: a release renaming one would fail every adopted repo's plan until edited, and a `moved` block can't redirect an import. Git history keeps the record.
- An adoption's plan shows each hand-made ruleset updating in place. A replacement there means the provider's import or `ForceNew` behaviour has changed, which is this ADR's revisit trigger.
- Repos whose push step was created under v1.0.0 keep their state: the step's command changes, but `triggers_replace` doesn't, so the step doesn't run again.

[ADR 001]: 001-share-the-github-repo-standard-as-a-versioned-terraform-module.md
[ADR 005]: 005-keep-personal-preferences-out-of-the-module.md
[`terraform_data.push`]: ../../main.tf
