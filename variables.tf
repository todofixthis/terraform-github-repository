variable "description" {
  description = "Repository description. Required, because GitHub shows it on the repo page and in search, and a repo without one says nothing about itself."
  type        = string
}

variable "homepage_url" {
  default     = null
  description = "Repository homepage URL, linking the repo to its docs (the templates pass the ReadTheDocs URL). Null for none, e.g. for a private repo whose docs ReadTheDocs can't build."
  type        = string
}

variable "local_path" {
  default     = null
  description = "A path inside the local git checkout whose develop and main the push step sends to the new repo. Needed because Terraform runs from the root module's directory, which isn't always inside that checkout. Null means the root module's directory, which suits a root module in the project's own infra/github/; git finds the checkout by walking up."
  type        = string
}

variable "name" {
  description = "Repository name, which fixes the repo's URL. Required, since no default could fit two repos."
  type        = string
}

variable "topics" {
  default     = []
  description = "Repository topics, so repos are findable by topic on GitHub. Optional."
  type        = list(string)
}

variable "visibility" {
  default     = "public"
  description = "Repository visibility: public or private. Lets a project start private; private also omits secret scanning and push protection, which need GitHub Advanced Security there."
  type        = string

  validation {
    condition     = contains(["private", "public"], var.visibility)
    error_message = "visibility must be \"public\" or \"private\"."
  }
}
