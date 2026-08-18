output "api_url" {
  description = "Public base URL of the API."
  value       = module.alb.api_url
}

output "domain_name" {
  description = "Public host name, as read from Parameter Store."
  value       = local.domain_name
}

output "alb_dns_name" {
  description = "DNS name of the load balancer, for a CNAME when Route 53 is not used."
  value       = module.alb.dns_name
}

output "swagger_url" {
  description = "Swagger UI."
  value       = "${module.alb.api_url}/swagger"
}

output "openapi_url" {
  description = "OpenAPI document."
  value       = "${module.alb.api_url}/openapi/v1.json"
}

output "ecr_repository_urls" {
  description = "Repository URL per image, for `docker push`."
  value       = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.compute.cluster_name
}

output "ecs_service_names" {
  description = "ECS service name per component."
  value       = module.compute.service_names
}

output "pipeline_run_task_command" {
  description = "Command that runs the data pipeline once against this environment."
  value       = module.compute.pipeline_run_task_command
}

output "migrations_run_task_command" {
  description = "Ready-made command that applies the database schema once."
  value       = module.compute.migrations_run_task_command
}

output "database_endpoint" {
  description = "RDS endpoint. It is reachable from the private subnets only."
  value       = module.rds.endpoint
}

output "database_password_secret_arn" {
  description = "Secrets Manager secret holding the database password. Read it with `aws secretsmanager get-secret-value`."
  value       = module.secrets.database_password_secret_arn
}

output "client_secret_arns" {
  description = "Secrets Manager secret per API client. Read one with `aws secretsmanager get-secret-value`."
  value       = module.secrets.client_secret_arns
}

output "parameter_root" {
  description = "Root of this environment's Parameter Store tree."
  value       = module.secrets.parameter_root
}

output "secret_prefix" {
  description = "Secrets Manager name prefix for this environment."
  value       = module.secrets.secret_prefix
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard for the platform."
  value       = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${module.monitoring.dashboard_name}"
}

output "log_group_names" {
  description = "CloudWatch log group per service."
  value       = module.compute.log_group_names
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes through OIDC, when one was created."
  value       = module.iam.github_deploy_role_arn
}

output "vpc_id" {
  description = "VPC identifier."
  value       = module.networking.vpc_id
}

# --- teardown ---------------------------------------------------------------------
# The teardown workflow turns off the two deletion guards that AWS enforces on
# the live resource, so it needs to name them.

output "database_identifier" {
  description = "RDS instance identifier. Used by the teardown workflow to turn deletion protection off."
  value       = module.rds.identifier
}

output "alb_arn" {
  description = "Load balancer ARN. Used by the teardown workflow to turn deletion protection off."
  value       = module.alb.arn
}

output "image_tag" {
  description = "Tag currently deployed. The teardown workflow reads it back so the disarm apply redeploys the same images rather than a placeholder."
  value       = var.image_tag
}
