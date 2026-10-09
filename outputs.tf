output "html_url" {
  description = "The repository's web URL."
  value       = github_repository.this.html_url
}

output "http_clone_url" {
  description = "The repository's HTTPS clone URL."
  value       = github_repository.this.http_clone_url
}

output "ssh_clone_url" {
  description = "The repository's SSH clone URL."
  value       = github_repository.this.ssh_clone_url
}
