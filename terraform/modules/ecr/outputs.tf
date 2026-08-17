output "repository_urls" {
  description = "Repository URL per short name, for `docker push`."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "repository_arns" {
  description = "Repository ARN per short name, for the task execution policy."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.arn }
}

output "registry_id" {
  description = "Account that owns the registry. It is the same for every repository, so the first one answers for all of them."
  value       = try(values(aws_ecr_repository.this)[0].registry_id, null)
}
