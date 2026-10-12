locals {
  # GitHub's numeric ID for the Admin repository role, used as a ruleset bypass actor
  admin_repository_role_id = 5
  # Secret scanning and push protection need GitHub Advanced Security on a private repo
  enable_security_and_analysis = var.visibility == "public"
  # The GitHub Actions app, which reports the `gate` check
  github_actions_integration_id = 15368
  push_path                     = coalesce(var.local_path, path.root)
  trunk_branches                = toset(["develop", "main"])
}

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
  has_issues             = true
  has_projects           = false
  has_wiki               = false
  homepage_url           = var.homepage_url
  merge_commit_message   = "PR_BODY"
  merge_commit_title     = "PR_TITLE"
  name                   = var.name
  topics                 = var.topics
  visibility             = var.visibility

  # Keep this exact for_each form: the tests assert the local, because the
  # block's absence is unknown at plan time
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

resource "github_repository_vulnerability_alerts" "this" {
  enabled    = true
  repository = github_repository.this.name
}

resource "github_repository_dependabot_security_updates" "this" {
  enabled    = false
  repository = github_repository.this.name

  depends_on = [github_repository_vulnerability_alerts.this]
}

# Pushes the local develop and main branches. Runs once per repo: it's
# replaced only when the repo is.
resource "terraform_data" "push" {
  triggers_replace = [github_repository.this.repo_id]

  provisioner "local-exec" {
    command = <<-EOT
      set -eu
      git remote get-url origin >/dev/null 2>&1 || git remote add origin "$SSH_URL"
      git push --no-verify origin develop main
    EOT
    environment = {
      SSH_URL = github_repository.this.ssh_clone_url
    }
    interpreter = ["/bin/sh", "-c"]
    working_dir = local.push_path
  }
}

resource "github_branch_default" "this" {
  branch     = "develop"
  repository = github_repository.this.name

  depends_on = [terraform_data.push]
}

# Created after the push: trunk-main has no bypass, so it would block the push
# that creates main
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

  # Dependents pin the module by tag, so blocking update stops even a
  # fast-forward move
  rules {
    deletion         = true
    non_fast_forward = true
    update           = true
  }

  depends_on = [github_branch_default.this]
}

resource "github_app_installation_repository" "renovate" {
  count = var.renovate_installation_id == null ? 0 : 1

  installation_id = var.renovate_installation_id
  repository      = github_repository.this.name
}
