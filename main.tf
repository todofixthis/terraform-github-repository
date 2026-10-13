locals {
  # GitHub's numeric ID for the Admin repository role, used as a ruleset bypass actor
  admin_repository_role_id = 5
  # Secret scanning and push protection need GitHub Advanced Security on a private repo
  enable_security_and_analysis = var.visibility == "public"
  # The GitHub Actions app, which reports the `gate` check
  github_actions_integration_id = 15368
  # The push step needs a checkout to push from; path.root sits inside the
  # project's own checkout when the root module lives in infra/github/
  push_path = coalesce(var.local_path, path.root)
  # The two long-lived branches; everything else is a short-lived PR branch
  trunk_branches = toset(["develop", "main"])
}

# The repo itself, carrying the merge and feature settings every todofixthis
# repo shares, so a setting changed in the UI shows up as drift in the next plan
resource "github_repository" "this" {
  allow_auto_merge       = false
  allow_merge_commit     = true
  allow_rebase_merge     = false
  allow_squash_merge     = false
  allow_update_branch    = false
  archive_on_destroy     = true
  delete_branch_on_merge = true
  description            = var.description
  has_discussions        = false
  # Enable even for private repos so that Renovate can post its dependency dashboard.
  has_issues           = true
  has_projects         = false
  has_wiki             = false
  homepage_url         = var.homepage_url
  merge_commit_message = "PR_BODY"
  merge_commit_title   = "PR_TITLE"
  name                 = var.name
  topics               = var.topics
  visibility           = var.visibility

  # Keep this exact for_each form. The private-repo test can't see the block's
  # absence at plan time, so it asserts local.enable_security_and_analysis
  # instead; a condition other than that local would leave the test passing
  # while checking nothing
  dynamic "security_and_analysis" {
    for_each = local.enable_security_and_analysis ? [1] : []

    content {
      secret_scanning {
        status = "enabled"
      }

      secret_scanning_push_protection {
        status = "enabled"
      }
    }
  }

  lifecycle {
    # The provider always sends has_downloads=false, and stores advanced_security
    # on read though it can't be set for public repos; either could otherwise
    # show a diff on every plan
    ignore_changes = [
      has_downloads,
      security_and_analysis[0].advanced_security,
    ]
  }
}

# Renovate reads Dependabot alerts to raise its security PRs, so alerts stay on
# even though Dependabot itself opens nothing. A resource of its own because the
# repo's vulnerability_alerts attribute is deprecated
resource "github_repository_vulnerability_alerts" "this" {
  enabled    = true
  repository = github_repository.this.name
}

# Managed, and off, so Renovate is the only thing opening update PRs; left
# unmanaged, a UI toggle would start a second, competing stream of PRs
resource "github_repository_dependabot_security_updates" "this" {
  enabled    = false
  repository = github_repository.this.name

  depends_on = [github_repository_vulnerability_alerts.this]
}

# Gives the new repo its first commits by pushing the local develop and main
# branches: the default branch and the rulesets below need both to exist. Runs
# once per repo: it's replaced only when the repo is.
resource "terraform_data" "push" {
  triggers_replace = [github_repository.this.repo_id]

  provisioner "local-exec" {
    command = <<-EOT
      set -eu
      # Only adds origin when there's none: an existing one may be a remote the
      # maintainer set up on purpose, so it's never replaced
      git remote get-url origin >/dev/null 2>&1 || git remote add origin "$SSH_URL"
      # --no-verify: the checkout's own pre-push hook would otherwise run a plan
      # against the state this apply is holding
      git push --no-verify origin develop main
    EOT
    environment = {
      SSH_URL = github_repository.this.ssh_clone_url
    }
    interpreter = ["/bin/sh", "-c"]
    working_dir = local.push_path
  }
}

# develop is where work lands, so making it the default points new PRs and
# clones at it without anyone having to choose. Follows the push, since the
# branch has to exist first
resource "github_branch_default" "this" {
  branch     = "develop"
  repository = github_repository.this.name

  depends_on = [terraform_data.push]
}

# Makes changes reach develop and main through PRs that pass an up-to-date
# gate check with review threads resolved, so untested code can't land on
# either. Only develop lets admins bypass, for the release back-merge. Created
# after the push: trunk-main has no bypass, so it would block the push that
# creates main
resource "github_repository_ruleset" "trunk" {
  for_each = local.trunk_branches

  enforcement = "active"
  name        = "trunk-${each.key}"
  repository  = github_repository.this.name
  target      = "branch"

  dynamic "bypass_actors" {
    for_each = each.key == "develop" ? [1] : []

    content {
      actor_id    = local.admin_repository_role_id
      actor_type  = "RepositoryRole"
      bypass_mode = "always"
    }
  }

  conditions {
    ref_name {
      exclude = []
      include = ["refs/heads/${each.key}"]
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      allowed_merge_methods             = ["merge"]
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_approving_review_count   = 0
      required_review_thread_resolution = true
    }

    required_status_checks {
      do_not_enforce_on_create             = false
      strict_required_status_checks_policy = true

      required_check {
        context        = "gate"
        integration_id = local.github_actions_integration_id
      }
    }
  }

  depends_on = [github_branch_default.this]
}

# Keeps each release tag pointing at what was released, for anyone who fetched
# or pinned it. For this module's own repo that matters most: dependents pin it
# by tag, so a moved tag would change what their next init fetches
resource "github_repository_ruleset" "tags_release" {
  enforcement = "active"
  name        = "tags-release"
  repository  = github_repository.this.name
  target      = "tag"

  conditions {
    ref_name {
      exclude = []
      include = ["~ALL"]
    }
  }

  # update is what blocks a fast-forward move; non_fast_forward alone only
  # blocks force-pushes
  rules {
    deletion         = true
    non_fast_forward = true
    update           = true
  }

  # Tag rules don't touch branches, so the push doesn't need this ordering; it
  # keeps all three rulesets landing together, after the repo has its branches
  depends_on = [github_branch_default.this]
}
