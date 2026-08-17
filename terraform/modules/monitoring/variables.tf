variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "cluster_name" {
  description = "ECS cluster name, used by the dashboard metric dimensions."
  type        = string
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix, used by the CloudWatch metric dimensions."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "Target group ARN suffix, used by the CloudWatch metric dimensions."
  type        = string
}

variable "database_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "trace_sample_rate" {
  description = "Fraction of requests traced beyond the reservoir, from 0 to 1."
  type        = number
  default     = 0.1

  validation {
    condition     = var.trace_sample_rate >= 0 && var.trace_sample_rate <= 1
    error_message = "trace_sample_rate must be between 0 and 1."
  }
}

variable "trace_reservoir_size" {
  description = "Traces per second always kept, before the sample rate applies."
  type        = number
  default     = 1
}

variable "error_count_threshold" {
  description = "Server errors per minute that trip the error alarm."
  type        = number
  default     = 5
}

variable "latency_p95_threshold_seconds" {
  description = "p95 latency that trips the latency alarm. The stated budget is 500 ms."
  type        = number
  default     = 0.5
}

variable "free_storage_threshold_bytes" {
  description = "Free database storage that trips the storage alarm."
  type        = number
  default     = 10737418240 # 10 GiB
}

variable "create_sns_topic" {
  description = "Create an SNS topic for the alarms. False uses alarm_action_arns instead."
  type        = bool
  default     = true
}

variable "sns_kms_key_id" {
  description = "KMS key for the SNS topic. Null uses no encryption at rest."
  type        = string
  default     = null
}

variable "alarm_action_arns" {
  description = "Existing targets for the alarms, used when create_sns_topic is false."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
