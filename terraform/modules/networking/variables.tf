variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "region" {
  description = "AWS region. Used to build VPC endpoint service names."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC. It must be large enough for three /20 subnets per availability zone."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && tonumber(split("/", var.vpc_cidr)[1]) <= 20
    error_message = "vpc_cidr must be a valid CIDR block of /20 or larger."
  }
}

variable "availability_zone_count" {
  description = "Number of availability zones to spread the subnets across."
  type        = number
  default     = 2

  validation {
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 4
    error_message = "availability_zone_count must be between 2 and 4. Two is the minimum for a highly available load balancer and RDS."
  }
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway for every private subnet. Cheaper, and a single point of failure. Suitable for a development environment only."
  type        = bool
  default     = false
}

variable "enable_interface_endpoints" {
  description = "Create interface VPC endpoints for ECR, CloudWatch Logs, Systems Manager and X-Ray. They cost an hourly rate per endpoint per AZ, and they keep image pulls and secret reads off the public internet."
  type        = bool
  default     = true
}

variable "flow_log_retention_days" {
  description = "Retention of the VPC flow logs, in days."
  type        = number
  default     = 30
}

variable "api_container_port" {
  description = "Port the API container listens on."
  type        = number
  default     = 8080
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
