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
