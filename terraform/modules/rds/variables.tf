variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "environment" {
  description = "Environment name, used in the final snapshot identifier."
  type        = string
}

variable "subnet_ids" {
  description = "Database subnets. They must have no route to the internet."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group of the instance. It should accept 5432 from the task security group only."
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL version. Must be 16 or later, and must carry pgvector 0.7 or later."
  type        = string
  default     = "16.14"

  validation {
    condition     = can(regex("^1[6-9]\\.", var.engine_version)) || can(regex("^[2-9][0-9]\\.", var.engine_version))
    error_message = "engine_version must be PostgreSQL 16 or later; pgvector 0.7 with HNSW is required."
  }
}

variable "instance_class" {
  description = "Instance class. A vector search is memory bound, so favour a memory optimised class in production."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage" {
  description = "Initial storage in gibibytes."
  type        = number
  default     = 50
}

variable "max_allocated_storage" {
  description = "Ceiling for storage autoscaling, in gibibytes. Set it equal to allocated_storage to switch autoscaling off."
  type        = number
  default     = 200
}

variable "database_name" {
  description = "Name of the application database."
  type        = string
  default     = "movies"
}

variable "database_username" {
  description = "Master user name."
  type        = string
  default     = "movies"
}

variable "database_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the master password. The ARN is not a secret; the value behind it is read ephemerally and never stored."
  type        = string
}

variable "database_password_version" {
  description = "Increment this after writing a new password to the secret. It is what tells Terraform the write-only password changed, because the value itself is never stored to compare against."
  type        = number
  default     = 1
}

variable "multi_az" {
  description = "Run a synchronous standby in another availability zone."
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "Days of automated backups to keep."
  type        = number
  default     = 7
}

variable "backup_window" {
  description = "Daily backup window, in UTC."
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "Weekly maintenance window, in UTC."
  type        = string
  default     = "sun:04:30-sun:05:30"
}

variable "deletion_protection" {
  description = "Refuse to delete the instance. Leave it on in production."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot on delete. Only ever true in a throwaway environment."
  type        = bool
  default     = false
}

variable "apply_immediately" {
  description = "Apply a change at once rather than in the next maintenance window."
  type        = bool
  default     = false
}

variable "performance_insights_enabled" {
  description = "Turn on Performance Insights."
  type        = bool
  default     = true
}

variable "enhanced_monitoring_interval" {
  description = "Enhanced monitoring interval in seconds. Zero switches it off."
  type        = number
  default     = 60

  validation {
    condition     = contains([0, 1, 5, 10, 15, 30, 60], var.enhanced_monitoring_interval)
    error_message = "enhanced_monitoring_interval must be one of 0, 1, 5, 10, 15, 30, 60."
  }
}

variable "kms_key_arn" {
  description = "Customer managed KMS key for storage encryption. Null uses the AWS managed RDS key."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
