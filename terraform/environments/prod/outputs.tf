output "api_url" {
  description = "Public base URL of the production API."
  value       = module.platform.api_url
}

output "swagger_url" {
  description = "Swagger UI."
  value       = module.platform.swagger_url
}

output "alb_dns_name" {
  description = "DNS name of the load balancer."
  value       = module.platform.alb_dns_name
}

output "ecr_repository_urls" {
  description = "Repository URL per image."
  value       = module.platform.ecr_repository_urls
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.platform.ecs_cluster_name
}

output "pipeline_run_task_command" {
  description = "Command that loads the dataset into this environment."
  value       = module.platform.pipeline_run_task_command
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard for this environment."
  value       = module.platform.cloudwatch_dashboard_url
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy this environment."
  value       = module.platform.github_deploy_role_arn
}

output "database_endpoint" {
  description = "RDS endpoint, as host:port. Reachable from the private subnets only, so a migration from a laptop needs an SSM port forward through a task in the VPC. See terraform/README.md."
  value       = module.platform.database_endpoint
}

output "database_password_secret_arn" {
  description = "Secrets Manager secret holding the database password."
  value       = module.platform.database_password_secret_arn
}

output "parameter_root" {
  description = "Root of this environment's Parameter Store tree."
  value       = module.platform.parameter_root
}

output "secret_prefix" {
  description = "Secrets Manager name prefix for this environment."
  value       = module.platform.secret_prefix
}

output "domain_name" {
  description = "Public host name, as read from Parameter Store."
  value       = module.platform.domain_name
}

output "database_identifier" {
  description = "RDS instance identifier. The teardown workflow uses it to turn deletion protection off."
  value       = module.platform.database_identifier
}

output "alb_arn" {
  description = "Load balancer ARN. The teardown workflow uses it to turn deletion protection off."
  value       = module.platform.alb_arn
}

output "image_tag" {
  description = "Tag currently deployed. Read back by the teardown workflow."
  value       = module.platform.image_tag
}
