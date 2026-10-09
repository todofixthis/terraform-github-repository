variable "description" {
  description = "Repository description."
  type        = string
}

variable "homepage_url" {
  default     = null
  description = "Repository homepage URL, or null for none."
  type        = string
}

variable "local_path" {
  default     = null
  description = "A path inside the local git checkout to push from. Null means the root module's directory; git finds the checkout by walking up."
  type        = string
}

variable "name" {
  description = "Repository name."
  type        = string
}

variable "renovate_installation_id" {
  default     = null
  description = "Installation ID of the Renovate GitHub App, or null to leave the repo out of Renovate's installation."
  type        = string
}

variable "topics" {
  default     = []
  description = "Repository topics."
  type        = list(string)
}

variable "visibility" {
  default     = "public"
  description = "Repository visibility: public or private."
  type        = string

  validation {
    condition     = contains(["private", "public"], var.visibility)
    error_message = "visibility must be \"public\" or \"private\"."
  }
}
