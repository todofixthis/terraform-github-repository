# This repo's own GitHub configuration, provisioned by the module it holds.
terraform {
  required_version = ">= 1.9"

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
  source = "../.."

  description              = "Terraform module for the standard GitHub repo configuration of todofixthis projects"
  name                     = "terraform-github-repository"
  renovate_installation_id = "60701509"
}
