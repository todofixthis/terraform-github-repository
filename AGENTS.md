## Getting Started

Before writing code, check `docs/adr/INDEX.md` for prior decisions (don't re-litigate).

## Architecture Decision Records

When making significant decisions — choosing between libraries, patterns, tools, or conventions — you **must** write an ADR before implementing the decision. Use the `phx:writing-adrs` skill for the format and conventions. ADRs live in `docs/adr/`.

## Commands

```bash
# Install the pre-push hook (once per clone; not in a cloud session)
git config core.hooksPath .githooks
# Format
terraform fmt -recursive
# Validate the module
terraform init -input=false -backend=false && terraform validate
# Validate this repo's own root; CI fails if init changes its committed lock
terraform -chdir=infra/github init -input=false -backend=false && terraform -chdir=infra/github validate
# Module tests (mock provider, plan only)
terraform test
# scripts/infra-plan and pre-push fixture tests
tests/infra-plan/test.sh
# Plan infra/github and post it to the branch's PR
scripts/infra-plan
```

## Architecture

- Repo root `*.tf` — the module: one GitHub repo with the todofixthis standard settings and rulesets.
- `infra/github/` — this repo's own configuration, provisioned by the module via `source = "../.."`. Source of truth for this repo's GitHub settings; never change them in the GitHub UI.
- `scripts/infra-plan` — canonical copy of the plan script. Each template repo (`todofixthis/cookiecutter-py`, `todofixthis/cookiecutter-browser-plugin`) ships a copy byte-identical to this one at the tag it pins; only `.infra-paths` differs. A script change therefore reaches a template only after release, copied by hand onto its module-bump PR (the Renovate PR bumping the module tag). The plan comment must start with `<!-- infra-plan -->`, which later runs use to find and update it, and carry `<!-- infra-hash: … -->`, which CI matches. Changing either means changing `.github/workflows/ci.yml` here in the same PR, and each template's generated-project workflow on its module-bump PR; projects already generated keep their old copies until updated by hand, so say so in the release notes.
- `tests/` — `terraform test` files, plus fixture tests for the script and hook.

## Module rules

- Create the rulesets whatever the visibility, and keep `archive_on_destroy = true` (ADR 001).
- Keep the `security_and_analysis` block's `for_each` exactly `local.enable_security_and_analysis ? [1] : []`; the tests rely on it.
- `terraform test` runs must stay `command = plan`: the push step is built in and unmocked.

## Infra changes

An infra change is one touching `infra/` or a root `*.tf` file.

Before opening its PR, run `scripts/infra-plan`; a non-zero exit is a failure to fix or report, whatever it printed. If it warns that terraform isn't installed or state isn't available, there is no plan: open the PR, then tell the user it needs a local plan before CI goes green, and that they unblock it with `gh pr checkout <n>` then `scripts/infra-plan`. Otherwise check the plan matches the intended change and report it, open the PR, and run the script again: it can only post the plan comment to an existing PR, and CI stays red until it does. If that run doesn't print `✅ plan posted`, act on its warning, or if you can't, tell the user the same.

If `init` fails on a PR that doesn't change the provider constraint, report the error rather than following the script's hint.

After an infra PR merges, the maintainer runs `terraform -chdir=infra/github apply` from an up-to-date `develop`.

Never write the plan comment by hand.

## Secrets

Never put secrets in Terraform: no `sensitive` inputs, no `*_secret` resources (ADR 002). Never handle a secret's value yourself either. Give the user the command to run, e.g. `gh secret set NPM_TOKEN -R todofixthis/terraform-github-repository`, and list the secret under a `## Secrets` heading in `README.md`.

## Releases

Before opening the release PR, bump the `?ref=` in `README.md`'s usage example to the new tag through an ordinary PR into `develop`. Then open the release PR from `develop` into `main`, and once it merges, tag `vX.Y.Z` (annotated) on `main`. Never move or delete a published tag: dependents fetch modules by tag, so a moved tag changes their next `init` without a bump PR or a plan. Merging `origin/main` back into `develop` (fast-forward when it can) and pushing uses the Admin bypass, so hand that push to the maintainer unless they've asked you to make it. Publish a GitHub release for the tag, with notes drafted by the `phx:writing-release-notes` skill. The notes call out any change to `scripts/infra-plan` (template repos need the copy) and any provider-constraint change (dependents need a lock update).

## Code Comments

Place comments on the line preceding the code they document, not as trailing comments.

## Language and Style

NZ English; incorporate Te Reo Māori where natural (e.g. "mahi", "kaupapa").

## Branches

- `main` — releases only; merge from `develop` via PR
- `develop` — main development branch
- Feature branches off `develop` for all new work

Open every PR against `develop` (`gh pr create --base develop`), unless it's a release PR. Until this repo's first apply its default branch is still `main`, and CI only checks for a plan on PRs into `develop`.
