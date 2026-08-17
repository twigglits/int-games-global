variable "project" {
  description = "Project name. It is the first segment of every parameter path."
  type        = string
}

variable "environment" {
  description = "Environment name. It is the second segment of every parameter path."
  type        = string
}

variable "api_client_ids" {
  description = "Client identifiers that may exchange credentials for an access token. One Secrets Manager secret is expected per identifier, under clients/."
  type        = list(string)
  default     = ["reader-client", "admin-client"]
}

variable "required_config_keys" {
  description = "Configuration keys that must exist under config/. A missing one fails the plan with an instruction rather than a null reference much later."
  type        = list(string)
  default     = ["domain-name"]
}
