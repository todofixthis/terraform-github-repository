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
# Infra-plan script and pre-push tests
uv run --no-project --with pytest pytest scripts/infra-plan
# Lint the script as generated projects will (CI runs the same; ADR 004)
uvx black --check scripts/infra-plan/infra_plan.py && uvx ruff check --isolated scripts/infra-plan/infra_plan.py && uvx mypy --strict scripts/infra-plan/infra_plan.py
# Plan infra/github and post it to the branch's PR (needs uv)
scripts/infra-plan/infra_plan.py
```

## Architecture

- Repo root `*.tf` — the module: one GitHub repo with the todofixthis standard settings and rulesets.
- `infra/github/` — this repo's own configuration, provisioned by the module via `source = "../.."`. Source of truth for this repo's GitHub settings; never change them in the GitHub UI.
- `scripts/infra-plan/` — the infra-plan script, `infra_plan.py` (Python, standard library only, run by uv; ADR 004), and its pytest tests. `infra_plan.py` is the canonical copy: each template repo (`todofixthis/cookiecutter-py`, `todofixthis/cookiecutter-browser-plugin`) ships a copy byte-identical to this one at the tag it pins; only `.infra-paths` differs. A script change therefore reaches a template only after release, copied by hand onto its module-bump PR (the Renovate PR bumping the module tag). The plan comment must start with `<!-- infra-plan -->`, which later runs use to find and update it; changing that marker leaves old comments unfound, so the next run posts a duplicate. It must also carry `<!-- infra-hash: … -->`, which CI matches: changing that means changing `.github/workflows/ci.yml` here in the same PR, and each template's generated-project workflow on its module-bump PR; projects already generated keep their old copies until updated by hand, so say so in the release notes.
- `tests/` — `terraform test` files for the module.

## Module rules

- Create the rulesets whatever the visibility, and keep `archive_on_destroy = true` (ADR 001).
- Keep the `security_and_analysis` block's `for_each` exactly `local.enable_security_and_analysis ? [1] : []`; the tests rely on it.
- `terraform test` runs must stay `command = plan`: the push step is built in and unmocked.

## Infra changes

An infra change is one touching `infra/` or a root `*.tf` file. A change this repo's own config doesn't use, such as a new module output, plans as "No changes", which is correct.

Before opening its PR, run `scripts/infra-plan/infra_plan.py`; a non-zero exit is a failure to fix or report, whatever it printed. If uv isn't installed the script can't start (exit 127); if it warns that terraform isn't installed or state isn't available, it ran but couldn't plan. Either way there is no plan: open the PR, then tell the maintainer it needs a local plan before CI goes green, and that they unblock it with `gh pr checkout <n>` then `scripts/infra-plan/infra_plan.py`.

Otherwise check the plan matches the intended change and report it, open the PR, and run the script again: it can only post the plan comment to an existing PR, and CI stays red until it does.

Act on every ⚠️ it prints, even after `✅ plan posted`. The usual one is "CI run still in progress": wait for that run with `gh run watch <id> --exit-status --interval 30 >/dev/null` (it redraws the whole run on every refresh, so read its exit code, not its output; run it in the background if your tool's timeout is shorter than a few minutes). A non-zero exit can also mean a GitHub API error cut the watch short, so check `gh run view <id> --json status,conclusion -q '.status + " " + .conclusion'`: anything but `completed` means watch again, up to three times before you report it. If it's `completed failure`, `gh run view <id>` shows which jobs. If only `infra-plan` and `gate` failed, `gh run rerun --failed <id>` and watch that run the same way; if it fails the same way again, run the script once more, and if that doesn't help, report it rather than rerunning. A run cancelled by a newer push is superseded: watch the newer one, the first `databaseId` from `gh run list --branch <branch> --event pull_request --limit 1 --json databaseId`. Anything else is a real failure to fix. Treat "✅ reran failed jobs" the same, as the first rerun: the PR isn't green until that run passes. If it doesn't print `✅ plan posted` at all, or you can't act on a warning, tell the maintainer the PR needs a local plan, as above.

If `init` fails on a PR that doesn't change the provider constraint, report the error rather than following the script's hint.

After an infra PR merges, the maintainer runs `terraform -chdir=infra/github apply` from an up-to-date `develop`.

Never write the plan comment by hand.

## Secrets

Never put secrets in Terraform: no `sensitive` inputs, no `*_secret` resources (ADR 002). Never handle a secret's value yourself either. Give the maintainer the command to run, e.g. `gh secret set NPM_TOKEN -R todofixthis/terraform-github-repository`, and list the secret under a `## Secrets` heading in `README.md`.

## Releases

Before opening the release PR, bump the `?ref=` in `README.md`'s usage example to the new tag through an ordinary PR into `develop`. Then open the release PR from `develop` into `main` and leave the merge to the maintainer. Once it merges, tag `vX.Y.Z` (annotated) on `main`, then merge `origin/main` back into `develop`. Never move or delete a published tag: dependents fetch modules by tag, so a moved tag changes their next `init` without a bump PR or a plan. That back-merge (fast-forward when it can) is pushed with the Admin bypass, so hand that push to the maintainer unless they've asked you to make it. Publish a GitHub release for the tag, with notes drafted by the `phx:writing-release-notes` skill. The notes call out any change to `scripts/infra-plan/infra_plan.py` (template repos need the copy, plus whatever the template-side consequences in its ADRs list, such as ADR 004's for the move to Python) and any provider-constraint change (dependents need a lock update).

## Code Comments

Place comments on the line preceding the code they document, not as trailing comments. The one exception is the version comment after a pinned action's SHA in a workflow (`uses: …@<sha> # v7.0.1`), which Renovate reads and updates.

Document why each of these exists, not what its code does: a reader new to the repo should learn its purpose from the doc comment alone, and a descriptive name doesn't count.

- **Every non-trivial function:** a docstring giving why it exists: one line where the summary already says why, otherwise a summary line then a paragraph. Add Google-style `Args:`/`Returns:` sections only where they say something the signature doesn't.
- **Every test:** a docstring (Python) or a preceding comment (a `terraform test` `run`) stating the scenario, so the tests double as documentation.
- **Every Terraform resource:** a preceding comment giving its raison d'être; `terraform_data.push` in `main.tf` is the model.
- **Every variable:** its `description` says why the input is needed, not only what it is.
- **Every output:** its `description` names the intended consumer, or says it's speculative and gives the anticipated use.

A new resource, input or output also goes in `README.md`'s "What it configures" list, inputs table or outputs line.

## Language and Style

Sort unordered collections alphabetically, Terraform attributes within a block included; meta-arguments keep HashiCorp's placement (`count`/`for_each` first, `depends_on` and `lifecycle` last).

NZ English; incorporate Te Reo Māori where natural (e.g. "mahi", "kaupapa").

## Branches

- `main` — releases only; merge from `develop` via PR
- `develop` — main development branch
- Feature branches off `develop` for all new work

Open every PR against `develop`, unless it's a release PR: CI only checks for a plan on PRs into `develop`.
