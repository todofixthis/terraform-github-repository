# terraform-github-repository

A Terraform module that creates a GitHub repo with the standard configuration of todofixthis projects, pushes its first commits, and applies its branch and tag rulesets. It can also adopt an existing repo (see [Adopting an existing repo](#adopting-an-existing-repo)).

## What it configures

- **Merging:** merge commits only, titled from the PR title and described from its body. Branches are deleted on merge; auto-merge and the "Update branch" button are off.
- **Features:** issues on; wiki, projects and discussions off.
- **Security:** secret scanning and push protection on for public repos; Dependabot alerts on; Dependabot security updates off (Renovate opens update PRs).
- **Branches:** `develop` is the default. `trunk-develop` and `trunk-main` block deletion and force-pushes, and require a PR with resolved threads and a passing, up-to-date `gate` check. The Admin role can bypass `trunk-develop`; nothing bypasses `trunk-main`.
- **Tags:** `tags-release` blocks deleting or moving any tag.
- **Destroy:** archives the repo rather than deleting it, after removing its rulesets and alert settings. The archived repo keeps its name, so applying again with the same `name` fails until you unarchive and `terraform import` it.

## Usage

```hcl
terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "github" {
  owner = "todofixthis"
}

module "repository" {
  source = "github.com/todofixthis/terraform-github-repository?ref=v1.1.0"

  description = "A short description of the project"
  name        = "my-project"
}
```

Declare `integrations/github` in your root module as above; without it Terraform assumes `hashicorp/github`.

Before the first apply:

- **Branches.** The push step pushes `develop` and `main` from the checkout containing your root module (or `local_path`), but only those the remote doesn't have yet, so both local branches must exist. From a `main`-only checkout, run `git branch develop main` first.
- **Remote.** If the checkout has no `origin`, the push step adds the new repo's SSH URL. An existing `origin` wins, so check it points at the repo being created.
- **Credentials.** The provider uses `GITHUB_TOKEN`, or `gh auth token` when that's unset. The push uses your own git SSH credentials.
- **A `gate` job.** Both trunk rulesets require a check named `gate` from GitHub Actions, and nothing bypasses `trunk-main`. Ship a workflow with a job of that name, or nothing can merge into `main`.

After the first apply:

- **Renovate.** If Renovate is installed for selected repositories only, add the new repo at <https://github.com/settings/installations> → Renovate → Configure → Repository access. The module can't do it: GitHub's installation endpoints reject the OAuth token `gh` uses, even for reads, so managing it in Terraform would need a PAT (untested) for every plan.
- **Watching.** Unless the new repo already shows as watched, click Watch → All Activity on it. The module leaves this out by design: a watch belongs to a person, not the repo ([ADR 005](docs/adr/005-keep-personal-preferences-out-of-the-module.md)).

| Input | Default | Notes |
|---|---|---|
| `name` | — | Repository name |
| `description` | — | Repository description |
| `homepage_url` | `null` | |
| `topics` | `[]` | |
| `visibility` | `"public"` | `"public"` or `"private"`. Private repos skip secret scanning and push protection. On GitHub Free, a private repo's rulesets may not be enforced. |
| `local_path` | root module directory | Any path inside the checkout to run `git push` from |

Outputs: `html_url`, `http_clone_url`, `ssh_clone_url`.

Going from private to public takes two steps, because the provider can't do it in one apply: run `gh repo edit <owner>/<name> --visibility public --accept-visibility-change-consequences`, then set `visibility = "public"` (or remove it) and plan and apply. Leave it `"private"` and the plan flips the repo back.

## Adopting an existing repo

To bring a repo that already exists under the module, import its settings rather than creating them ([ADR 006](docs/adr/006-adopt-existing-repos-by-import-pushing-only-missing-branches.md)). The checklists under [Usage](#usage) still apply: in particular, the repo's CI needs a job named `gate`, or nothing can merge once the rulesets apply.

1. **Sync the trunk branches.** Fetch, and make sure local `develop` and `main` exist. The push step pushes only the branches the remote lacks, so for a `main`-only repo, local `develop` becomes the remote's: branch it from an up-to-date `main`. If a hand-made ruleset there already covers `develop` without a bypass, it blocks that push and the apply fails, so narrow it to `main` first.
2. **List the repo's rulesets:** `gh api repos/<owner>/<name>/rulesets -q '.[] | "\(.id) \(.name) \(.target)"'`.
3. **Add `import` blocks** to the root module, beside the `module` block. Import each hand-made ruleset under the module address it most resembles, so the apply that takes it over also rewrites it and a branch already protected stays protected. A ruleset covering both trunk branches becomes `trunk["develop"]`, and the module creates `trunk["main"]`, leaving `main` unprotected for the seconds between the two. Leave out any address with no ruleset to import, and the module creates it.

   ```hcl
   import {
     id = "my-project"
     to = module.repository.github_repository.this
   }

   import {
     id = "my-project"
     to = module.repository.github_repository_vulnerability_alerts.this
   }

   import {
     id = "my-project"
     to = module.repository.github_repository_dependabot_security_updates.this
   }

   import {
     id = "my-project"
     to = module.repository.github_branch_default.this
   }

   import {
     # <repo>:<ruleset id>, from step 2
     id = "my-project:12345678"
     to = module.repository.github_repository_ruleset.trunk["develop"]
   }

   import {
     id = "my-project:12345679"
     to = module.repository.github_repository_ruleset.trunk["main"]
   }

   # Only where the repo already has a tag ruleset
   import {
     id = "my-project:12345680"
     to = module.repository.github_repository_ruleset.tags_release
   }
   ```

4. **Set the module's inputs to match the repo.** `visibility` defaults to `"public"`, so a private repo needs `visibility = "private"`. Set `description`, `homepage_url` and `topics` to the repo's current values too, unless you mean to change them: the plan overwrites them with the inputs.
5. **Plan.** Each import shows beside the changes it makes. Read the `github_repository` diff as closely as the rulesets: an unintended visibility or description change there is an ordinary update. Apart from the new push step, nothing should be created except module rulesets you didn't import, and anything replaced or destroyed means stop and check before applying.
6. **Apply, and delete any ruleset left over.** A hand-made ruleset you didn't import still applies alongside the module's.

Then remove the `import` blocks in a follow-up PR. Left in, a module release that renames one of these addresses would fail the repo's plan.

## Previewing infra changes

State is local to the maintainer's machine (`infra/github/terraform.tfstate`, gitignored, backed up by hand), so CI can't plan. `scripts/infra-plan/infra_plan.py` (needs [uv](https://docs.astral.sh/uv/)) plans on your machine and posts the plan to the branch's PR. On PRs into `develop`, CI's `infra-plan` job fails until a plan comment from an owner or collaborator matches the PR's current infra files.

Run `git config core.hooksPath .githooks` once per clone, and the pre-push hook runs the script whenever a push of the checked-out branch changes the infra files. The script can only post to an existing PR, so on a new branch: push, open the PR, then run `scripts/infra-plan/infra_plan.py` yourself. For a PR you didn't push (Renovate, a cloud agent), run `gh pr checkout <n>` then `scripts/infra-plan/infra_plan.py`.

After an infra PR merges, run `terraform -chdir=infra/github apply` from an up-to-date `develop`.

## Rolling out a release

Every repo using the module keeps its state on the maintainer's machine, and its CI runs no plan, so nothing stops a module bump merging without a plan or sitting unapplied after it merges ([cookiecutter-py ADR 025](https://github.com/todofixthis/cookiecutter-py/blob/develop/docs/adr/025-ship-github-settings-as-terraform-planned-by-hand.md)). That's deliberate: a person reviews every change to a repo's GitHub settings. This repo needs nothing more, since its own config follows the module through `source = "../.."` and was applied when each infra PR merged. If the release notes say the provider constraint moved to a new major, follow [A release that moves the provider constraint](#a-release-that-moves-the-provider-constraint) instead of steps 1 and 2. Otherwise, after publishing a release:

1. **Update the templates.** In each template repo that ships `infra/github/` (today, todofixthis/cookiecutter-py), Renovate opens a PR bumping the module pin, in `template/infra/github/main.tf.jinja` for cookiecutter-py. Its CI bakes a project and validates it against the new release. Merge it, then release the template, following that repo's AGENTS.md.
2. **Update each project.** A project gets a Renovate PR bumping its pin directly, a template-update PR carrying the new pin, or both. On each, plan from your machine:

   ```bash
   gh pr checkout <n>
   terraform -chdir=infra/github init -input=false
   terraform -chdir=infra/github plan
   ```

   Check the plan against the release notes. If `init` rewrote `.terraform.lock.hcl`, commit it to the PR. Merge, then apply from an up-to-date `develop`:

   ```bash
   git checkout develop && git pull --ff-only
   terraform -chdir=infra/github apply
   ```

   Where a project gets both PRs, merge whichever arrives first. On its next run Renovate closes the direct bump once the pin is current, and a template update landing on a different version conflicts on the pin's line: keep the higher version.
3. **Check nothing was missed.** This lists every repo whose default branch pins the module, in `infra/github/main.tf` or a template's `template/infra/github/main.tf.jinja`, flagging any pinned behind the latest release:

   ```bash
   latest=$(gh api repos/todofixthis/terraform-github-repository/releases/latest -q .tag_name)
   for r in $(gh repo list todofixthis --no-archived --limit 200 --json name -q '.[].name'); do
     for f in infra/github/main.tf template/infra/github/main.tf.jinja; do
       ref=$(gh api "repos/todofixthis/$r/contents/$f" -H 'Accept: application/vnd.github.raw' 2>/dev/null | rg -o 'terraform-github-repository\?ref=(v[0-9.]+)' -r '$1')
       if [ -n "$ref" ]; then
         echo "$r $ref$([ "$ref" = "$latest" ] || echo " (behind $latest)")"
       fi
     done
   done
   ```

   A repo flagged behind with no open bump PR usually means Renovate hasn't run there yet, or can't reach it: check the repo's Dependency Dashboard issue, and its access at <https://github.com/settings/installations>.

   A bump merged but never applied only shows in a plan. With each project checked out under one directory (`~/Documents` below), this plans every checkout that holds state, naming the branch each is on:

   ```bash
   for d in ~/Documents/*/infra/github; do
     [ -f "$d/terraform.tfstate" ] || continue
     repo=${d%/infra/github}
     branch=$(git -C "$repo" branch --show-current)
     terraform -chdir="$d" init -input=false >/dev/null 2>&1
     terraform -chdir="$d" plan -detailed-exitcode -input=false -lock=false >/dev/null 2>&1
     case $? in
       0) echo "$repo ($branch): applied" ;;
       2) echo "$repo ($branch): CHANGES PENDING, review and apply" ;;
       *) echo "$repo ($branch): plan failed, run it by hand" ;;
     esac
   done
   ```

   It reports only what's checked out with state, so match every project from the pin check against a line here: a missing one hasn't been checked. A result means something only for a checkout on an up-to-date `develop`. A repo reported as pending needs its plan reviewed and applied as in step 2.

### A release that moves the provider constraint

The release notes say so when the module's `integrations/github` constraint moves to a new major. Each project's own root module pins the provider too (`~> 6.0` in the template's `main.tf.jinja`), and the template's Renovate rule never offers a provider major, so a direct module bump alone fails `init`. This repo's own `infra/github/main.tf` pins it too, so the module PR moving the constraint moves that line as well; its plan fails `init` until it does. Then:

1. In the template, raise the provider constraint in `template/infra/github/main.tf.jinja` on the same PR as the module bump, then release the template. The template repo's own Renovate config doesn't block provider majors, so it may open a separate PR raising that constraint: close it, or fold its change into the module bump, since merged alone it bakes projects whose module pin can't use the new provider.
2. In each project, close the direct module-bump PR and take the template update, which moves both lines. Plan it with `terraform -chdir=infra/github init -input=false -upgrade`, which rewrites the lock for the new provider, then `plan`. Commit the new lock to the PR, then merge and apply as in **Update each project** above.
