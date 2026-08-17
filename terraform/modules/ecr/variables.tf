variable "name_prefix" {
  description = "Prefix applied to every repository name."
  type        = string
}

variable "repository_names" {
  description = "Short names of the repositories to create, one per image."
  type        = list(string)
  default     = ["api", "mcp-server", "pipeline"]
}

variable "image_tag_mutability" {
  description = "IMMUTABLE keeps a pushed tag pointing at the same bytes for ever. Use MUTABLE only if a workflow overwrites a tag on purpose."
  type        = string
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "force_delete" {
  description = "Allow `terraform destroy` to remove a repository that still holds images. True in a development environment, false in production."
  type        = bool
  default     = false
}

variable "kms_key_arn" {
  description = "Customer managed KMS key for image encryption. Null uses the AES256 encryption ECR provides by default."
  type        = string
  default     = null
}

variable "untagged_expiry_days" {
  description = "Days an untagged image survives before the lifecycle policy expires it."
  type        = number
  default     = 7
}

variable "retained_image_count" {
  description = "Number of recent tagged images to keep per repository."
  type        = number
  default     = 20
}

variable "tags" {
  description = "Tags applied to every repository."
  type        = map(string)
  default     = {}
}
