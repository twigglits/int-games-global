# --- configuration -----------------------------------------------------------

output "domain_name" {
  description = "Public host name of the API."
  value       = local.config_or_null["domain-name"]
}

output "route53_zone_id" {
  description = "Hosted zone that owns the domain, or null when DNS is managed elsewhere."
  value       = lookup(local.config_or_null, "route53-zone-id", null)
}

output "certificate_arn" {
  description = "Existing ACM certificate, or null to have Terraform request one."
  value       = lookup(local.config_or_null, "certificate-arn", null)
}

output "github_oidc_provider_arn" {
  description = "GitHub Actions OIDC provider, or null to skip the deployment role."
  value       = lookup(local.config_or_null, "github-oidc-provider-arn", null)
}

output "alarm_topic_arn" {
  description = "Existing SNS topic for the alarms, or null to have Terraform create one."
  value       = lookup(local.config_or_null, "alarm-topic-arn", null)
}

output "alb_access_logs_bucket" {
  description = "S3 bucket for load balancer access logs, or null to switch them off."
  value       = lookup(local.config_or_null, "alb-access-logs-bucket", null)
}

output "config" {
  description = "Every configuration parameter found, for debugging."
  value       = local.config_or_null
}

# --- secrets -------------------------------------------------------------------
# ARNs only. An ARN is not a secret. No module in this configuration reads a
# secret value, except the RDS module, which reads the database password through
# an ephemeral resource.

output "database_password_secret_arn" {
  description = "Secrets Manager secret holding the database master password."
  value       = data.aws_secretsmanager_secret.database_password.arn
}

output "jwt_signing_key_secret_arn" {
  description = "Secrets Manager secret holding the API token signing key."
  value       = data.aws_secretsmanager_secret.jwt_signing_key.arn
}

output "client_secret_arns" {
  description = "Secrets Manager secret per API client identifier."
  value       = local.client_secret_arns
}

output "readable_secret_arns" {
  description = "Every secret the ECS task execution role is allowed to read."
  value       = local.readable_secret_arns
}

output "config_parameter_arns" {
  description = "Parameter Store prefix the deployment role may read, so Terraform can resolve the configuration."
  value       = local.config_parameter_arns
}

output "secret_prefix" {
  description = "Secrets Manager name prefix for this environment. Secrets Manager names have no leading slash."
  value       = local.secret_prefix
}

output "parameter_root" {
  description = "Root path of this environment's Parameter Store tree."
  value       = local.root
}
