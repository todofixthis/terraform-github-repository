# Lookups into blocks a regression could remove go through try(), so it fails
# its own run instead of erroring and skipping every run after it.
#
# Plan-only: the mock provider doesn't cover the built-in terraform_data push
# step, so `command = apply` would really run `git push`.
mock_provider "github" {}

variables {
  description = "Test repository"
  name        = "test-repository"
}

# A repo built with the defaults gets the standard settings, so every repo
# merges the same way: merge commits only, branches deleted on merge, issues as
# the only feature, and archive on destroy so a stray destroy keeps history
run "repo_settings_match_the_standard" {
  command = plan

  assert {
    condition = (
      github_repository.this.allow_merge_commit
      && !github_repository.this.allow_squash_merge
      && !github_repository.this.allow_rebase_merge
      && !github_repository.this.allow_auto_merge
      && !github_repository.this.allow_update_branch
      && github_repository.this.delete_branch_on_merge
    )
    error_message = "Merge settings must be merge-commit only, with branch deletion on merge."
  }

  assert {
    condition = (
      github_repository.this.has_issues
      && !github_repository.this.has_wiki
      && !github_repository.this.has_projects
      && !github_repository.this.has_discussions
    )
    error_message = "Only issues may be enabled among the repo features."
  }

  assert {
    condition     = github_repository.this.archive_on_destroy
    error_message = "A destroy must archive the repo, not delete it."
  }
}

# A public repo, the default, turns on secret scanning and push protection, so
# a leaked credential is caught before or soon after it lands
run "public_repo_enables_secret_scanning" {
  command = plan

  assert {
    condition     = local.enable_security_and_analysis
    error_message = "A public repo must enable security_and_analysis."
  }

  assert {
    condition     = try(github_repository.this.security_and_analysis[0].secret_scanning[0].status, null) == "enabled"
    error_message = "A public repo must enable secret scanning."
  }

  assert {
    condition     = try(github_repository.this.security_and_analysis[0].secret_scanning_push_protection[0].status, null) == "enabled"
    error_message = "A public repo must enable push protection."
  }
}

# A private repo leaves secret scanning out, since it needs GitHub Advanced
# Security there and the apply would fail
run "private_repo_omits_secret_scanning" {
  command = plan

  variables {
    visibility = "private"
  }

  assert {
    condition     = !local.enable_security_and_analysis
    error_message = "A private repo must omit security_and_analysis."
  }
}

# A visibility other than public or private ("internal" exists only for
# enterprise organisations) is refused at plan time rather than at the API
run "visibility_rejects_other_values" {
  command = plan

  variables {
    visibility = "internal"
  }

  expect_failures = [var.visibility]
}

# main takes changes only through a PR, even from an admin, so every release
# arrives as a merge from develop that passed the gate check
run "trunk_main_has_no_bypass" {
  command = plan

  assert {
    condition     = length(github_repository_ruleset.trunk["main"].bypass_actors) == 0
    error_message = "trunk-main must have no bypass actor."
  }
}

# develop lets the Admin role bypass, which the release back-merge needs, and
# nobody else
run "trunk_develop_bypass_is_admin_only" {
  command = plan

  assert {
    condition     = length(github_repository_ruleset.trunk["develop"].bypass_actors) == 1
    error_message = "trunk-develop must have exactly one bypass actor."
  }

  assert {
    condition = (
      try(github_repository_ruleset.trunk["develop"].bypass_actors[0].actor_id, null) == 5
      && try(github_repository_ruleset.trunk["develop"].bypass_actors[0].actor_type, null) == "RepositoryRole"
      && try(github_repository_ruleset.trunk["develop"].bypass_actors[0].bypass_mode, null) == "always"
    )
    error_message = "trunk-develop's bypass actor must be the Admin role, always."
  }
}

# Both trunk branches target their own ref, require an up-to-date passing gate
# check from GitHub Actions, and accept merge commits only, so untested or
# out-of-date code can't land on either and history keeps every merge
run "trunk_rulesets_require_strict_gate_and_merge_only" {
  command = plan

  assert {
    condition = alltrue([
      for branch in ["develop", "main"] :
      try(one(github_repository_ruleset.trunk[branch].conditions[0].ref_name[0].include), null) == "refs/heads/${branch}"
    ])
    error_message = "Each trunk ruleset must target its own branch."
  }

  assert {
    condition = alltrue([
      for branch in ["develop", "main"] :
      try(github_repository_ruleset.trunk[branch].rules[0].required_status_checks[0].strict_required_status_checks_policy, false)
    ])
    error_message = "Both trunk rulesets must require branches to be up to date."
  }

  assert {
    condition = alltrue([
      for branch in ["develop", "main"] :
      length(try(github_repository_ruleset.trunk[branch].rules[0].required_status_checks[0].required_check, [])) == 1
      && anytrue([
        for check in try(github_repository_ruleset.trunk[branch].rules[0].required_status_checks[0].required_check, []) :
        check.context == "gate" && check.integration_id == 15368
      ])
    ])
    error_message = "Both trunk rulesets must require exactly the gate check from GitHub Actions."
  }

  assert {
    condition = alltrue([
      for branch in ["develop", "main"] :
      toset(try(github_repository_ruleset.trunk[branch].rules[0].pull_request[0].allowed_merge_methods, [])) == toset(["merge"])
    ])
    error_message = "Both trunk rulesets must allow merge commits only."
  }
}

# Every tag is protected from deletion, force-pushes and moves, with no bypass,
# so a release tag keeps pointing at what was released
run "tags_ruleset_covers_all_tags" {
  command = plan

  assert {
    condition = (
      github_repository_ruleset.tags_release.target == "tag"
      && try(one(github_repository_ruleset.tags_release.conditions[0].ref_name[0].include), null) == "~ALL"
      && length(github_repository_ruleset.tags_release.bypass_actors) == 0
    )
    error_message = "tags-release must cover every tag with no bypass actor."
  }

  # update is the rule that blocks a fast-forward move
  assert {
    condition = (
      try(github_repository_ruleset.tags_release.rules[0].deletion, false)
      && try(github_repository_ruleset.tags_release.rules[0].non_fast_forward, false)
      && try(github_repository_ruleset.tags_release.rules[0].update, false) == true
    )
    error_message = "tags-release must block deleting, force-pushing and moving tags."
  }
}
