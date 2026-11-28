---
status: Accepted
date: 2026-11-27
scope: [infra/, main.tf, outputs.tf, variables.tf, versions.tf, AGENTS.md, README.md, tests/]
summary: Provision every todofixthis repo on the develop/main trunk model through this versioned module, pinned by tag and updated by Renovate PRs that are never auto-merged, not through per-template HCL copies or one central repo; the module creates its rulesets only for a public repo, never a private one, archives on destroy, and leaves Renovate membership and the private main-only repos to be set by hand.
revisit-when: The todofixthis account becomes a GitHub organisation. GitHub stops refusing rulesets on a private repo the todofixthis account owns. Terraform authenticates with a credential GitHub's App installation endpoints accept. A private repo takes up the develop/main trunk model and a gate job.
---

# 008: Share the GitHub repo standard as a versioned module, with rulesets on public repos only

## Context

[ADR 001][] made this module the home of the todofixthis GitHub standard: `develop`/`main` trunks, merge commits only, a single required `gate` check, tag protection, and the security settings. It also had the module create its rulesets whatever the visibility, on the unverified guess that GitHub Free would accept them on a private repo without enforcing them. It set a trigger for that guess: "A private repo's apply shows GitHub refusing rulesets."

The guess is wrong. On 2026-11-27, GitHub answered both `GET …/rulesets` and `GET …/branches/main/protection` with `403 Upgrade to GitHub Pro or make this repository public to enable this feature` on all seven private repos the todofixthis account owns: config-claude, config-leash, config-opencode, config-paddock, forex-fee-calculator, notion-data and portfolio. The one exception is practical-ai-for-devs, a private fork of an organisation's repo, which answers normally; a fork isn't the module's to manage. Even reads are refused, so the account gets no branch or tag protection of either kind on a private repo it owns. No create was attempted, since that writes to a live repo, but a create that reached the same check would fail the same way. As the module stands, a fresh private apply creates the repo, pushes its branches and sets its default branch, then fails at the first ruleset, and so does every apply after it. That breaks the `visibility = "private"` input, which exists so a project can start private and open up later.

The same survey showed that the seven repos don't follow the standard anyway. All seven have `main` only. Their history mixes PR merges with direct pushes, and config-claude's own workflow pushes to `main`. notion-data, portfolio and config-opencode have no workflows, so they have no `gate` job.

## Options

### Option 1: Do nothing

Keep creating the rulesets whatever the visibility.

**Pros:** No change to the module or its addresses.
**Cons:** The `visibility = "private"` input fails every apply, so the input is known to be broken.
**Risks:** A project started private is left half-created, with the repo pushed and its default branch set but nothing protecting it, until someone works out why every apply fails.

### Option 2: Create the rulesets only for a public repo (Accepted)

`trunk` and `tags_release` are created only where `visibility` is `"public"`. A private repo gets everything else: its settings, its alert settings, its push and its default branch.

**Pros:** A project can start private, and gets its rulesets in the first apply after it goes public.
**Cons:** `tags_release` takes a `count`, so its address becomes `tags_release[0]`. Terraform moves existing state there by itself. An `import` block naming the old address fails `terraform validate` ("The target resource is using count"), so it stops a plan rather than half-applying.
**Risks:** Going public is a `gh repo edit` followed by an apply, and between the two the repo is public with no rulesets and no secret scanning.

### Option 3: Make the module public-only

Drop the `visibility` input.

**Pros:** One shape to test, and no address change.
**Cons:** A project can't be created private through the module. It would have to be created by hand, then adopted by import once public.
**Risks:** None beyond losing that path.

### Option 4: Keep creating them everywhere, on GitHub Pro

Pay for GitHub Pro, which GitHub's own refusal names as the fix.

**Pros:** A project started private gets enforced protection from its first apply, and no address changes.
**Cons:** A recurring cost, to protect repos during a private phase none has needed yet.
**Risks:** Moving back to Free later brings the refusal back on every managed private repo at once.

## Decision

Option 2. Starting private is speculative: no project has done it through the module, and the account's private repos all live on `main` alone. But the input already exists, and keeping it costs one condition and one address change. Option 3 would save those at the price of a working path. Option 4 pays every month for a private phase that a project can do without, as long as it lands its `gate` job before going public.

The rest of ADR 001 stands as it was:

- **A versioned module, pinned `?ref=vX.Y.Z`.** Each repo's `infra/github/` root calls the module by tag, and Renovate's [Terraform manager][] opens the bump PRs. They're never auto-merged: a change to the standard is a release that each dependent adopts through a normal PR, planned by hand before it merges and applied by hand after ([cookiecutter-py ADR 025][]). Keeping a person in that loop is a security control, since GitHub settings are a wide attack surface. Per-template HCL copies would drift. One central repo would put every repo in one state and one blast radius, and baking a project would mean editing a second repo first. Organisation-level rulesets would replace most of the module, but todofixthis is a personal account.
- **`archive_on_destroy = true`.** A stray `destroy`, or a module refactor that renames `github_repository.this` without a `moved` block, archives the repo rather than deleting its history. In the rename case the archived repo keeps its name, so the same apply's create fails half-done. Recovery is a manual unarchive plus `terraform import`.
- **Renovate membership stays manual.** Renovate is installed for selected repos only, so each repo is added to its installation by hand after the first apply. The provider's `github_app_installation_repository` would do it, but GitHub's installation endpoints reject the OAuth token `gh auth token` returns. The read the resource makes on every plan fails and names the token type (checked 2026-10-12, on a token with `repo` scope). Keeping it in Terraform would mean a PAT, untested, on the maintainer's machine for every plan.
- **The release App, next iteration.** Terraform can't create GitHub Apps, so the design is one existing shared App, passed in by slug, with one key to rotate and one identity in each ruleset's bypass list. Adding each repo to that App's installation meets the same token rejection as Renovate, so that part is still open.

### The existing private repos stay out

The seven private repos stay configured by hand rather than adopted. Without rulesets, the module would bring them only drift detection on their merge, feature and alert settings. Adoption would also move each repo's default branch to a new `develop`, which breaks config-claude's publish workflow and the direct pushes the others take. A settings-only mode, skipping the trunk model for such repos, was rejected: it's a second module shape to test and maintain for repos whose settings rarely change. A breach would be authored in one of those repos' own `infra/github/`, which no path here reaches. The README's adoption section is the defence, and it meets the reader only if they open it.

## Consequences

- A dependent still holding the old address, such as filters-iso, plans a move and no change on its next bump, as this repo's own plan showed. Terraform makes that move implicitly when `count` is added; the module's explicit `moved` block only records it.
- The README's adoption example now names `tags_release[0]`. cookiecutter-py's 2.0.0 CHANGELOG entry still names the bare `tags_release`, which is right for its v1.1.0 pin. The template's entry for the bump to this release must say so. None of the five projects still to adopt has a tag ruleset (checked 2026-11-27).
- A private repo's plan creates no ruleset. Its two-step move to public ends with a plan that creates all three.
- Setting `visibility = "private"` on a managed public repo works in one apply. The plan's graph runs the three ruleset deletes before the visibility update, so they reach GitHub while the repo is still public (checked with `terraform graph` on a scratch copy of this repo's root and state set to private, planned but not applied). Making a managed repo private outside Terraform, with `gh repo edit` or the UI, leaves the rulesets in state on a repo where GitHub refuses even reads. Every later plan then fails at refresh until the repo is public again.
- The module owns the provider constraint, so every dependent's `renovate.json` disables major updates for `integrations/github`. A new major arrives only through a module release.
- A release that moves the `integrations/github` constraint leaves dependents' lock files stale, since Renovate doesn't update locks on module bumps. The README's "A release that moves the provider constraint" covers the rollout. Release notes must call out any provider-constraint change, any address a `moved` block shifts, and any change to what a visibility gets.
- A dependent's first `apply`, and any that replaces the push step, runs this module's `local-exec` with the maintainer's credentials, fetched by tag. `tags-release` blocks deleting, force-pushing and moving tags, so a `?ref=` pin always fetches what was released. It mustn't be weakened, and this repo must stay public for it to apply.
- A repo left out of Renovate's installation at bootstrap silently never gets module bumps, so each template's README must list adding it as a bootstrap step.
- `require_extra_approval_for_unattributed_changes` can't be set by the provider, so new repos get GitHub's default and drift there goes undetected.

[ADR 001]: 001-share-the-github-repo-standard-as-a-versioned-terraform-module.md
[cookiecutter-py ADR 025]: https://github.com/todofixthis/cookiecutter-py/blob/develop/docs/adr/025-ship-github-settings-as-terraform-planned-by-hand.md
[Terraform manager]: https://docs.renovatebot.com/modules/manager/terraform/
