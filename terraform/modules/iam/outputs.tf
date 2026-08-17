# The `depends_on` blocks below are about destroy ordering, not create ordering.
#
# A policy attached to a role is a graph leaf: nothing references it, so nothing
# depends on it. Terraform is therefore free to delete the policies at the same
# moment it is deleting the ECS services that are still draining tasks with those
# roles. A task that loses `secretsmanager:GetSecretValue` mid-drain fails its
# stop sequence, and the service takes the full timeout to go away.
#
# Putting `depends_on` on the *output* pushes that dependency onto every consumer
# of the output. The compute module reads these ARNs, so it now transitively
# depends on the policies — which means on destroy the services are torn down
# first and the policies afterwards, which is the order reality wants.
#
# It cannot be expressed as `module "iam" { depends_on = [module.compute] }`,
# because compute already depends on iam. That would be a cycle.

output "execution_role_arn" {
  description = "Role the ECS agent assumes to start a task."
  value       = aws_iam_role.execution.arn

  depends_on = [
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy_attachment.execution_managed,
  ]
}

output "task_role_arn" {
  description = "Role the application assumes once it is running."
  value       = aws_iam_role.task.arn

  depends_on = [aws_iam_role_policy.task]
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes through OIDC, or null when none was created."
  value       = try(aws_iam_role.github_deploy[0].arn, null)
}
