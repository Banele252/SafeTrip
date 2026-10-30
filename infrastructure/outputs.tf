output "html_url" {
  description = "Web address of the repository."
  value       = github_repository.safetrip.html_url
}

output "http_clone_url" {
  description = "HTTPS clone URL."
  value       = github_repository.safetrip.http_clone_url
}

output "ssh_clone_url" {
  description = "SSH clone URL, used for the git remote."
  value       = github_repository.safetrip.ssh_clone_url
}
