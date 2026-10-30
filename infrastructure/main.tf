terraform {
  required_version = ">= 1.5"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

# The token is read from the GITHUB_TOKEN environment variable, never from this file.
provider "github" {
  owner = var.github_owner
}

resource "github_repository" "safetrip" {
  name        = var.repository_name
  description = var.repository_description
  visibility  = "public"

  has_issues   = true
  has_projects = false
  has_wiki     = false

  # The local repository already has history, so GitHub must not create its own first commit.
  auto_init = false

  delete_branch_on_merge = true

  topics = ["raspberry-pi", "object-detection", "fastapi", "python"]
}

resource "github_repository_vulnerability_alerts" "safetrip" {
  repository = github_repository.safetrip.name
  enabled    = true
}
