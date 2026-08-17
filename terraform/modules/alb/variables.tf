variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "vpc_id" {
  description = "VPC the target group belongs to."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets the load balancer runs in. At least two, in different availability zones."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) >= 2
    error_message = "An Application Load Balancer needs subnets in at least two availability zones."
  }
}

variable "security_group_id" {
  description = "Security group of the load balancer."
  type        = string
}

variable "api_container_port" {
  description = "Port the API container listens on."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Path the target group polls. The readiness route reports on the whole chain behind the API."
  type        = string
  default     = "/health/ready"
}

variable "domain_name" {
  description = "Public host name of the API, for example api.movies.example.com."
  type        = string
}

variable "subject_alternative_names" {
  description = "Extra names on the certificate, when one is requested here."
  type        = list(string)
  default     = []
}

variable "certificate_arn" {
  description = "ARN of an existing ACM certificate. Null requests a new one and validates it through Route 53."
  type        = string
  default     = null
}

variable "route53_zone_id" {
  description = "Hosted zone that owns the domain. Required when a certificate is requested here, and used for the alias record."
  type        = string
  default     = null
}

variable "ssl_policy" {
  description = "TLS policy for the HTTPS listener."
  type        = string
  default     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}

variable "idle_timeout_seconds" {
  description = "Seconds an idle connection is held open. It must exceed the API request timeout."
  type        = number
  default     = 60
}

variable "enable_deletion_protection" {
  description = "Refuse to delete the load balancer. Leave it on in production."
  type        = bool
  default     = true
}

variable "access_logs_bucket" {
  description = "S3 bucket for access logs. Null switches access logging off."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
