# --- identity ----------------------------------------------------------------

variable "project" {
  description = "Project name. It prefixes every resource name and becomes the Project tag."
  type        = string
  default     = "movie-search"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project))
    error_message = "project must be lowercase letters, digits and hyphens, 2 to 21 characters."
  }
}

variable "environment" {
  description = "Environment name. It prefixes every resource name and becomes the Environment tag."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Team that owns the environment. Becomes the Owner tag."
  type        = string
  default     = null
}

variable "cost_centre" {
  description = "Cost centre the environment bills to. Becomes the CostCentre tag."
  type        = string
  default     = null
}

variable "repository_url" {
  description = "Source repository. Becomes the Repository tag, so an unfamiliar resource can be traced back to its code."
  type        = string
  default     = "https://github.com/example/movie-search-platform"
}

variable "extra_tags" {
  description = "Additional tags merged into every resource."
  type        = map(string)
  default     = {}
}

# --- networking ----------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "availability_zone_count" {
  description = "Availability zones to spread across."
  type        = number
  default     = 2
}

variable "single_nat_gateway" {
  description = "One NAT gateway instead of one per zone. Cheaper, and a single point of failure."
  type        = bool
  default     = false
}

variable "enable_interface_endpoints" {
  description = "Create the ECR, CloudWatch, Systems Manager and X-Ray interface endpoints."
  type        = bool
  default     = true
}

# --- load balancer and DNS ------------------------------------------------------
# The domain, the certificate, the hosted zone, the alarm topic and the access
# log bucket all come from Parameter Store now. See modules/secrets.

# --- database --------------------------------------------------------------------

variable "database_engine_version" {
  description = "PostgreSQL version. Must carry pgvector 0.7 or later."
  type        = string
  default     = "16.14"
}

variable "database_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "database_allocated_storage" {
  description = "Initial storage in gibibytes."
  type        = number
  default     = 50
}

variable "database_max_allocated_storage" {
  description = "Ceiling for storage autoscaling, in gibibytes."
  type        = number
  default     = 200
}

variable "database_name" {
  description = "Name of the application database."
  type        = string
  default     = "movies"
}

variable "database_username" {
  description = "Master user name. The password lives in Parameter Store and is never read by Terraform."
  type        = string
  default     = "movies"
}

variable "database_password_version" {
  description = "Increment after writing a new password to /<project>/<environment>/secrets/database-password. Terraform cannot see the write-only password to compare it, so this counter is what tells it to apply the change."
  type        = number
  default     = 1
}

variable "database_multi_az" {
  description = "Run a synchronous standby in a second availability zone."
  type        = bool
  default     = true
}

variable "database_backup_retention_days" {
  description = "Days of automated backups to keep."
  type        = number
  default     = 7
}

# --- teardown ---------------------------------------------------------------------

variable "force_destroy" {
  description = <<-EOT
    Disarm the guards that stop `terraform destroy` from completing:

      * no final RDS snapshot is taken
      * ECR repositories are deleted along with the images in them
      * RDS and ALB deletion protection are declared off

    It is false everywhere except the teardown workflow. Setting it on a normal
    apply removes the protection that stops a production database from being
    deleted by accident.

    The final snapshot and the ECR force delete are config-time: they are read
    off the configuration during the destroy itself, so passing this flag on
    `terraform destroy` is enough for both.

    Deletion protection is different, and it is the reason this flag has to be
    applied before it is destroyed with. RDS and ALB deletion protection are
    enforced by AWS on the live resource, and **a destroy plan contains only
    delete actions** — Terraform never emits an update while destroying, so it
    would never turn the flag off. It would go straight to the delete call and
    the API would refuse it.

    So the teardown is two Terraform runs, not one:

      terraform apply   -var force_destroy=true \
                        -target=module.platform.module.rds.aws_db_instance.this \
                        -target=module.platform.module.alb.aws_lb.this
      terraform destroy -var force_destroy=true

    The first flips the two flags in place. The second has nothing left to be
    refused by. `depends_on` cannot substitute for this: it orders resources
    against each other, it cannot make Terraform perform an update it never
    planned.
  EOT
  type        = bool
  default     = false
}

# --- application ------------------------------------------------------------------

variable "image_tag" {
  description = "Tag of the images to deploy. The delivery workflow sets it to the commit SHA."
  type        = string
  default     = "latest"
}

variable "image_tag_mutability" {
  description = "Whether an ECR tag may be overwritten."
  type        = string
  default     = "IMMUTABLE"
}

variable "api_container_port" {
  description = "Port the API listens on."
  type        = number
  default     = 8080
}

variable "mcp_transport" {
  description = "MCP transport. `http` is the production default; `sse` matches Docker Compose."
  type        = string
  default     = "http"
}

variable "embedding_model_id" {
  description = "Model the embedding service loads. Changing it means re-running the pipeline and changing the vector column width."
  type        = string
  default     = "BAAI/bge-base-en-v1.5"
}

variable "embedding_dimension" {
  description = "Vector width. It must match the vector(n) column in the migration."
  type        = number
  default     = 768
}

variable "reader_client_id" {
  description = "Client identifier granted the reader role."
  type        = string
  default     = "reader-client"
}

variable "admin_client_id" {
  description = "Client identifier granted the admin role."
  type        = string
  default     = "admin-client"
}

variable "auth_audience" {
  description = "Audience claim on the tokens the API mints."
  type        = string
  default     = "movie-search-api"
}

# --- sizing --------------------------------------------------------------------------

variable "api_cpu" {
  description = "CPU units per API task."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory in mebibytes per API task."
  type        = number
  default     = 1024
}

variable "api_desired_count" {
  description = "Starting number of API tasks."
  type        = number
  default     = 2
}

variable "api_min_capacity" {
  description = "Fewest API tasks autoscaling may leave running."
  type        = number
  default     = 2
}

variable "api_max_capacity" {
  description = "Most API tasks autoscaling may start."
  type        = number
  default     = 10
}

variable "mcp_cpu" {
  description = "CPU units per MCP task."
  type        = number
  default     = 512
}

variable "mcp_memory" {
  description = "Memory in mebibytes per MCP task."
  type        = number
  default     = 1024
}

variable "mcp_desired_count" {
  description = "Starting number of MCP tasks."
  type        = number
  default     = 2
}

variable "mcp_min_capacity" {
  description = "Fewest MCP tasks autoscaling may leave running."
  type        = number
  default     = 2
}

variable "mcp_max_capacity" {
  description = "Most MCP tasks autoscaling may start."
  type        = number
  default     = 8
}

variable "embeddings_cpu" {
  description = "CPU units per embedding task."
  type        = number
  default     = 2048
}

variable "embeddings_memory" {
  description = "Memory in mebibytes per embedding task."
  type        = number
  default     = 4096
}

variable "embeddings_min_capacity" {
  description = "Fewest embedding tasks autoscaling may leave running."
  type        = number
  default     = 1
}

variable "embeddings_max_capacity" {
  description = "Most embedding tasks autoscaling may start."
  type        = number
  default     = 4
}

variable "spot_weight" {
  description = "Weight of Fargate Spot in the capacity provider strategy. Zero uses on-demand only."
  type        = number
  default     = 0
}

# --- operations ----------------------------------------------------------------------

variable "enable_execute_command" {
  description = "Allow a shell into a running task. Useful in dev; it opens a shell into production if left on."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Retention of the CloudWatch log groups, in days."
  type        = number
  default     = 30
}

variable "trace_sample_rate" {
  description = "Fraction of requests traced beyond the X-Ray reservoir."
  type        = number
  default     = 0.1
}

variable "github_subject_patterns" {
  description = "Allowed values of the GitHub OIDC `sub` claim."
  type        = list(string)
  default     = []
}
