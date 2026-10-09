## Getting Started

Before writing code, check `docs/adr/INDEX.md` for prior decisions (don't re-litigate).

## Architecture Decision Records

When making significant decisions — choosing between libraries, patterns, tools, or conventions — you **must** write an ADR before implementing the decision. Use the `phx:writing-adrs` skill for the format and conventions. ADRs live in `docs/adr/`.

## Commands

```bash
git config core.hooksPath .githooks                       # install the pre-push hook (once per clone)
terraform fmt -recursive                                  # format
terraform init -backend=false && terraform validate       # validate the module
terraform test                                            # module tests (mock provider, plan only)
tests/infra-plan/test.sh                                  # scripts/infra-plan and pre-push fixture tests
scripts/infra-plan                                        # plan infra/github and post it to the branch's PR
```

## Architecture

- Repo root `*.tf` — the module: one GitHub repo with the todofixthis standard settings and rulesets.
- `infra/github/` — this repo's own configuration, provisioned by the module via `source = "../.."`. Source of truth for this repo's GitHub settings; never change them in the GitHub UI.
- `scripts/infra-plan` — canonical copy of the plan script. Each template repo ships a byte-identical copy, so a change here needs copying into `todofixthis/cookiecutter-py` and `todofixthis/cookiecutter-browser-plugin`; only `.infra-paths` differs between repos.
- `tests/` — `terraform test` files, plus fixture tests for the script and hook.

## Infra changes

- Before opening a PR that touches `infra/` or a root `*.tf` file, run `scripts/infra-plan`, check the plan matches the intended change, and report it. If it warns that terraform isn't installed or state isn't available, tell the user the PR needs a local plan before CI goes green. If `init` fails on a PR that doesn't bump the provider, report the error rather than following the script's hint.
- After an infra PR merges, the maintainer runs `terraform -chdir=infra/github apply` from an up-to-date `develop`.
- Never write the plan marker comment by hand.
- Never put secrets in Terraform: no `sensitive` inputs, no `github_actions_secret`. Set secrets with `gh secret set`.
- Keep the `security_and_analysis` block's `for_each` exactly `local.enable_security_and_analysis ? [1] : []`; the tests rely on it.
- `terraform test` runs must stay `command = plan`: the push step is built in and unmocked.

## Releases

Tag `vX.Y.Z` on `main` after merging a release PR from `develop`, then merge `origin/main` into `develop` (fast-forward when it can) and push. Release notes call out any change to `scripts/infra-plan` (template repos need the copy) and any provider-constraint change (dependents need a lock update).

## Code Comments

Place comments on the line preceding the code they document, not as trailing comments.

## Language and Style

NZ English; incorporate Te Reo Māori where natural (e.g. "mahi", "kaupapa").

## Branches

- `main` — releases only; merge from `develop` via PR
- `develop` — main development branch
- Feature branches off `develop` for all new work
