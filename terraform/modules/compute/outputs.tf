output "cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ARN of the ECS cluster."
  value       = aws_ecs_cluster.this.arn
}

output "service_names" {
  description = "Name of each long-running service."
  value = {
    api        = aws_ecs_service.api.name
    mcp_server = aws_ecs_service.mcp_server.name
    embeddings = aws_ecs_service.embeddings.name
  }
}

output "pipeline_task_definition_arn" {
  description = "Task definition the delivery workflow runs after a deployment."
  value       = aws_ecs_task_definition.pipeline.arn
}

output "pipeline_run_task_command" {
  description = "Ready-made command that runs the data pipeline once."
  value = join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.this.name}",
    "--task-definition ${aws_ecs_task_definition.pipeline.family}",
    "--launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", var.private_subnet_ids)}],securityGroups=[${var.security_group_id}],assignPublicIp=DISABLED}'",
  ])
}

output "migrations_run_task_command" {
  description = "Ready-made command that applies the schema once."
  value = join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.this.name}",
    "--task-definition ${aws_ecs_task_definition.migrations.family}",
    "--launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", var.private_subnet_ids)}],securityGroups=[${var.security_group_id}],assignPublicIp=DISABLED}'",
  ])
}

output "service_discovery_namespace" {
  description = "Private DNS namespace used for service to service calls."
  value       = aws_service_discovery_private_dns_namespace.this.name
}

output "log_group_names" {
  description = "CloudWatch log group per service."
  value       = { for name, group in aws_cloudwatch_log_group.service : name => group.name }
}
