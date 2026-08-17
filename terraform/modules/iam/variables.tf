variable "name_prefix" {
  description = "Prefix applied to every role name."
  type        = string
}

variable "secret_arns" {
  description = "Secrets Manager secrets the task execution role may read. Listing them explicitly is what keeps the role from reading every secret in the account."
  type        = list(string)
  default     = []
}

variable "config_parameter_arns" {
  description = "Parameter Store paths the deployment role may read, so Terraform can resolve this environment's configuration. Nothing under these paths is a secret."
  type        = list(string)
  default     = []
}

variable "secrets_kms_key_arn" {
  description = "KMS key that encrypts the secrets, when a customer managed key is used. Null uses the AWS managed key for Secrets Manager, and the policy is confined with a kms:ViaService condition instead."
  type        = string
  default     = null
}

variable "ecr_repository_arns" {
  description = "Repositories the deployment role may push to."
  type        = list(string)
  default     = []
}

variable "enable_execute_command" {
  description = "Allow `aws ecs execute-command` into a running task. Useful in a development environment; it opens a shell into production if left on."
  type        = bool
  default     = false
}

variable "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider in this account. Null skips the deployment role, for an account that deploys another way."
  type        = string
  default     = null
}

variable "github_subject_patterns" {
  description = "Values the GitHub OIDC `sub` claim may take, for example repo:owner/name:ref:refs/heads/main."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to every role."
  type        = map(string)
  default     = {}
}
