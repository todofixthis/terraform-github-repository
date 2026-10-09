---
status: Accepted
date: 2026-10-09
scope: [infra/, main.tf, outputs.tf, variables.tf, versions.tf]
summary: Provision every todofixthis repo through this versioned module, pinned by tag and updated by Renovate, not through per-template HCL copies or one central repo; the module creates rulesets whatever the visibility and archives on destroy.
revisit-when: A private repo's apply shows GitHub refusing rulesets. The todofixthis account becomes a GitHub organisation.
---

# 001: Share the GitHub repo standard as a versioned Terraform module

## Context

Every project baked from `todofixthis/cookiecutter-py` or `todofixthis/cookiecutter-browser-plugin` needs the same GitHub configuration: `develop`/`main` trunks, merge commits only, a single required `gate` check, tag protection, and the security settings taken from [`todofixthis/phx-claude-siat`][]'s live repo. Until now each repo was configured by hand in the UI, so the settings drift and nothing records why they are what they are. The standard will change: the next iteration adds a release App and its bypass. Whatever carries it must get a change to every existing repo, not only to newly baked ones.

## Options

### Option 1: Do nothing

**Pros:** No Terraform, state or tooling to maintain.
**Cons:** Every new repo is configured by hand from memory; settings such as wiki and projects stay at GitHub's defaults because nobody chose otherwise.
**Risks:** Drift between repos goes unnoticed until a missing ruleset lets a force-push or an unreviewed merge through.

### Option 2: A shared module, pinned `?ref=vX.Y.Z` (Accepted)

The standard lives here as a module; each repo's `infra/github/` root calls it by tag.

**Pros:** One reviewed definition; a change is a release, and each dependent repo adopts it through a normal PR that shows its plan.
**Cons:** A release takes a tag, plus a bump PR in every dependent repo, each needing a local plan.
**Risks:** A release that moves the provider constraint or changes `scripts/infra-plan` needs hand work in each dependent or template repo (see Consequences).

### Option 3: HCL copied into each template

**Pros:** No module repo, no tags.
**Cons:** A baked project keeps whatever HCL it was baked with; a change to the standard reaches existing projects only by hand-editing each one.
**Risks:** The copies diverge silently, which is the drift the IaC exists to stop.

### Option 4: One central repo managing every repo in one state

**Pros:** One `apply` updates every repo; no version bumps.
**Cons:** Baking a project means editing a second repo before the first can exist; one state file and one blast radius for everything.
**Risks:** A bad change or a corrupt state touches every repo at once.

## Decision

Option 2. It keeps each project self-describing (its own `infra/github/` and state) while giving the standard one home, and Renovate already runs on every repo involved (on a generated project, once the module adds it to Renovate's installation through `renovate_installation_id`): its [Terraform manager][] recognises `github.com/<owner>/<repo>?ref=<tag>` sources and opens the bump PRs. The plan comment on each bump PR shows what the new version would change on that repo before it's applied. Organisation-level rulesets would replace most of the module, but todofixthis is a personal account.

Three choices about the module belong with it:

- **`archive_on_destroy = true`.** A stray `destroy`, or a module refactor that renames `github_repository.this` without a `moved` block, archives the repo rather than deleting its history. The cost, in the rename case: the archived repo keeps its name, so the same apply's create fails half-done, and recovery is a manual unarchive plus `terraform import`.
- **Rulesets on private repos.** The maintainer is on GitHub Free, where rulesets on a private repo presumably need Pro. The module creates them whatever the visibility, accepting that they may exist without being enforced; they enforce as soon as the repo goes public. That GitHub accepts them rather than refusing is unverified. Under refusal, a fresh private `apply` stops after the repo is created, pushed and given its default branch. Later plans would propose the rulesets again, so every apply fails; for a repo whose rulesets are already in state (one made private after being public), `plan` may fail at refresh too, and then the plan-comment guard can't pass. The answer then is to create the rulesets for public repos only.
- **The release App, next iteration.** Terraform can't create GitHub Apps (the provider has no resource for it), so each repo can't own one. The design is one existing shared App, passed in by slug (for the App ID) plus its installation ID: one key to rotate, and one identity in each ruleset's bypass list.

## Consequences

- Module bumps reach generated projects as Renovate PRs, never auto-merged, each held until the maintainer plans it locally ([ADR 003][]).
- The module owns the provider constraint, so every dependent's `renovate.json` disables major updates for `integrations/github`; a new major arrives only through a module release.
- A release that moves the `integrations/github` constraint leaves dependents' lock files stale; Renovate doesn't update locks on module bumps. Where the locked version no longer satisfies the constraint, the fix is `terraform init -upgrade` plus `terraform providers lock` for `darwin_amd64`, `darwin_arm64`, `linux_amd64` and `linux_arm64`, on each bump branch; where `init` only rewrote the lock's constraints line, committing that rewrite is enough. Release notes must call out any provider-constraint change.
- A release that changes [`scripts/infra-plan`][] fails each template repo's byte-identical check until the script is copied across by hand. Generated projects keep their old copy.
- A dependent's first `apply`, and any that replaces the push step, runs this module's `local-exec` with the maintainer's credentials, fetched by tag. `tags-release` blocks deleting and force-pushing tags, so a `?ref=` pin can't be pointed at unrelated history; it has no `update` rule, matching `todofixthis/phx-claude-siat`, so a fast-forward move of a tag isn't blocked and the pin also trusts the maintainer not to make one.
- `require_extra_approval_for_unattributed_changes` can't be set by the provider, so new repos get GitHub's default and drift there goes undetected.

[ADR 003]: 003-gate-infra-prs-on-a-locally-posted-plan-comment.md
[`scripts/infra-plan`]: ../../scripts/infra-plan
[Terraform manager]: https://docs.renovatebot.com/modules/manager/terraform/
[`todofixthis/phx-claude-siat`]: https://github.com/todofixthis/phx-claude-siat
