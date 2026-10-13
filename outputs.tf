output "html_url" {
  description = "The repository's web URL. Speculative: nothing consumes it yet; anticipated for a root module to re-export, so `terraform output` shows where the new repo lives after the first apply."
  value       = github_repository.this.html_url
}

output "http_clone_url" {
  description = "The repository's HTTPS clone URL. Speculative: nothing consumes it yet; anticipated for tooling that clones without SSH keys, such as CI."
  value       = github_repository.this.http_clone_url
}

output "ssh_clone_url" {
  description = "The repository's SSH clone URL. Speculative: nothing consumes it yet; anticipated for pointing an existing checkout's origin at the new repo, since the push step won't replace an origin that's already set."
  value       = github_repository.this.ssh_clone_url
}
