---
status: Accepted
date: 2026-10-09
scope: [infra/, main.tf, outputs.tf, variables.tf]
summary: Never pass a secret through Terraform (no `sensitive` inputs, no `*_secret` resources such as `github_actions_secret`); set secrets with `gh secret set`.
revisit-when: The provider gains write-only secret attributes. Repo config moves to remote state with CI-run plans.
---

# 002: Keep secrets out of Terraform state

## Context

Repo config is applied from the maintainer's machine with local state (`infra/github/terraform.tfstate`, gitignored). Projects will need Actions secrets (a release App's private key next iteration, publishing tokens), and the provider offers resources that set them: `github_actions_secret`, `github_actions_environment_secret`, `github_dependabot_secret`, `github_codespaces_secret`. Terraform stores every attribute it manages in state in plain text, including values marked `sensitive`, which only hides them from plan output. Plans are also posted to PR comments ([ADR 003][]), which are public on a public repo, so an attribute that isn't marked `sensitive` would be published there too.

## Options

### Option 1: Do nothing

Secrets are set through whichever route is to hand, Terraform included.

**Pros:** Secrets declared beside the rest of the repo's config.
**Cons:** Nothing says which route is canonical, so the same secret may be managed twice.
**Risks:** A secret lands in an unencrypted state file on a laptop, in its backups, and in any copy of it shared to debug a plan.

### Option 2: `gh secret set` outside Terraform (Accepted)

**Pros:** The secret goes straight from the maintainer's machine to GitHub's encrypted store; nothing else ever holds it.
**Cons:** Which secrets a repo needs isn't declared in its IaC, so it has to be documented.
**Risks:** A forgotten secret surfaces only as a failing workflow.

### Option 3: Remote encrypted state (S3/GCS with KMS, or HCP Terraform) holding secrets

**Pros:** Secrets declared in IaC; state encrypted at rest.
**Cons:** A cloud account, a backend, and credentials to bootstrap before the first repo can exist; the secret still sits in state, readable by anyone who can read the backend.
**Risks:** The backend's access policy becomes part of every secret's security.

### Option 4: `github_actions_secret` with a pre-encrypted value

The resource's `value_encrypted` takes the secret already encrypted against the repo's public key, so state holds only ciphertext.

**Pros:** Secrets declared in IaC with no plaintext in state.
**Cons:** Every rotation of the secret means encrypting it against the repo's public key out of band, a step no simpler than `gh secret set`.
**Risks:** The ciphertext sits in a repo that may be public, permanently. After the repo's key rotates, a recreate sends ciphertext for a retired key.

## Decision

Option 2. Local state can't be made safe to hold plaintext secrets, and a remote backend is out of proportion to a handful of repos run by one maintainer. Secrets go through `gh secret set`, which never writes the value anywhere but GitHub. Option 4 keeps plaintext out, but its costs outweigh its one gain: noticing a secret changed or deleted outside Terraform.

A breach is visible in review: a module input or root variable marked `sensitive`, or any of the provider's `*_secret` resources, in any root `*.tf` file or under `infra/`. These are review signals rather than the mechanism: a variable's value never reaches state, but a resource attribute or output fed from it does. The provider's own token (`GITHUB_TOKEN`, or `gh auth token`) isn't a breach: Terraform uses it but never stores it.

## Consequences

- Each project's docs list the secrets it needs and the `gh secret set` command for each.
- Terraform can't detect a missing or stale secret.
- Write-only attributes (Terraform 1.11 and later) would let the provider take a secret without storing it; integrations/github 6.13 has none, and adopting them would also mean raising `required_version` from 1.9.
- Moving to remote state with CI-run plans reopens this too: CI would then need every secret Terraform manages as an input.

[ADR 003]: 003-gate-infra-prs-on-a-locally-posted-plan-comment.md
