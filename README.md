# terraform-github-repository

A Terraform module that creates a GitHub repo with the standard configuration of todofixthis projects, pushes its first commits, and applies its branch and tag rulesets.

## What it configures

- **Merging:** merge commits only, titled from the PR title and described from its body. Branches are deleted on merge; auto-merge and the "Update branch" button are off.
- **Features:** issues on; wiki, projects and discussions off.
- **Security:** secret scanning and push protection on for public repos; Dependabot alerts on; Dependabot security updates off (Renovate opens update PRs).
- **Branches:** `develop` is the default. `trunk-develop` and `trunk-main` block deletion and force-pushes, and require a PR with resolved threads and a passing, up-to-date `gate` check. The Admin role can bypass `trunk-develop`; nothing bypasses `trunk-main`.
- **Tags:** `tags-release` blocks deleting or force-pushing any tag.
- **Destroy:** archives the repo rather than deleting it, after removing its rulesets and alert settings and taking it out of Renovate's installation. The archived repo keeps its name, so applying again with the same `name` fails until you unarchive and `terraform import` it.

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
  source = "github.com/todofixthis/terraform-github-repository?ref=v1.0.0"

  description = "A short description of the project"
  name        = "my-project"
}
```

Declare `integrations/github` in your root module as above; without it Terraform assumes `hashicorp/github`.

Before the first apply:

- **Branches.** The push step runs `git push origin develop main` from the checkout containing your root module (or `local_path`), so both local branches must exist. From a `main`-only checkout, run `git branch develop main` first.
- **Remote.** If the checkout has no `origin`, the push step adds the new repo's SSH URL. An existing `origin` wins, so check it points at the repo being created.
- **Credentials.** The provider uses `GITHUB_TOKEN`, or `gh auth token` when that's unset. The push uses your own git SSH credentials.
- **A `gate` job.** Both trunk rulesets require a check named `gate` from GitHub Actions, and nothing bypasses `trunk-main`. Ship a workflow with a job of that name, or nothing can merge into `main`.

| Input | Default | Notes |
|---|---|---|
| `name` | — | Repository name |
| `description` | — | Repository description |
| `homepage_url` | `null` | |
| `topics` | `[]` | |
| `visibility` | `"public"` | `"public"` or `"private"`. Private repos skip secret scanning and push protection. On GitHub Free, a private repo's rulesets may not be enforced. |
| `renovate_installation_id` | `null` | Adds the repo to that Renovate installation |
| `local_path` | root module directory | Any path inside the checkout to run `git push` from |

Outputs: `html_url`, `http_clone_url`, `ssh_clone_url`.

Going from private to public takes two steps, because the provider can't do it in one apply: run `gh repo edit <owner>/<name> --visibility public --accept-visibility-change-consequences`, then set `visibility = "public"` (or remove it) and plan and apply. Leave it `"private"` and the plan flips the repo back.

## Previewing infra changes

State is local to the maintainer's machine (`infra/github/terraform.tfstate`, gitignored, backed up by hand), so CI can't plan. `scripts/infra-plan` plans on your machine and posts the plan to the branch's PR. On PRs into `develop`, CI's `infra-plan` job fails until a plan comment from an owner or collaborator matches the PR's current infra files.

Run `git config core.hooksPath .githooks` once per clone, and the pre-push hook runs the script whenever a push of the checked-out branch changes the infra files. The script can only post to an existing PR, so on a new branch: push, open the PR, then run `scripts/infra-plan` yourself. For a PR you didn't push (Renovate, a cloud agent), run `gh pr checkout <n>` then `scripts/infra-plan`.

After an infra PR merges, run `terraform -chdir=infra/github apply` from an up-to-date `develop`.
