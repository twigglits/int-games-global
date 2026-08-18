variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "vpc_id" {
  description = "VPC the cluster runs in."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets the tasks run in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group shared by the tasks."
  type        = string
}

variable "execution_role_arn" {
  description = "Role the ECS agent uses to start a task."
  type        = string
}

variable "task_role_arn" {
  description = "Role the application uses once it is running."
  type        = string
}

# --- images ------------------------------------------------------------------

variable "api_image" {
  description = "Fully qualified image of the .NET API, including the tag."
  type        = string
}

variable "mcp_image" {
  description = "Fully qualified image of the MCP server, including the tag."
  type        = string
}

variable "pipeline_image" {
  description = "Fully qualified image of the data pipeline, including the tag."
  type        = string
}

variable "migrations_image" {
  description = "Flyway image carrying this commit's SQL, as repository URL plus tag."
  type        = string
}

variable "embeddings_image" {
  description = "Image of the embedding model server."
  type        = string
  default     = "ghcr.io/huggingface/text-embeddings-inference:cpu-1.7"
}

variable "otel_collector_image" {
  description = "Image of the AWS Distro for OpenTelemetry collector sidecar."
  type        = string
  default     = "public.ecr.aws/aws-observability/aws-otel-collector:latest"
}

# --- database ----------------------------------------------------------------

variable "database_host" {
  description = "Host name of the RDS instance."
  type        = string
}

variable "database_port" {
  description = "Port of the RDS instance."
  type        = number
  default     = 5432
}

variable "database_name" {
  description = "Name of the application database."
  type        = string
  default     = "movies"
}

variable "database_username" {
  description = "Master user name. Not a secret, so it is a plain environment variable."
  type        = string
  default     = "movies"
}

variable "database_password_secret_arn" {
  description = "Secrets Manager secret holding the database password. The ECS agent reads it; Terraform never does."
  type        = string
}

# --- API secrets -------------------------------------------------------------

variable "jwt_signing_key_secret_arn" {
  description = "Secrets Manager secret holding the token signing key."
  type        = string
}

variable "reader_client_id" {
  description = "Client identifier granted the reader role."
  type        = string
  default     = "reader-client"
}

variable "reader_client_secret_arn" {
  description = "Secrets Manager secret holding the reader client secret."
  type        = string
}

variable "admin_client_id" {
  description = "Client identifier granted the admin role."
  type        = string
  default     = "admin-client"
}

variable "admin_client_secret_arn" {
  description = "Secrets Manager secret holding the admin client secret."
  type        = string
}

# --- application settings ----------------------------------------------------

variable "api_container_port" {
  description = "Port the API listens on."
  type        = number
  default     = 8080
}

variable "api_target_group_arn" {
  description = "Target group the API service registers with."
  type        = string
}

variable "mcp_transport" {
  description = "MCP transport. `http` (streamable HTTP) in production; `sse` matches the local default."
  type        = string
  default     = "http"

  validation {
    condition     = contains(["http", "sse"], var.mcp_transport)
    error_message = "mcp_transport must be http or sse."
  }
}

variable "service_discovery_namespace" {
  description = "Private DNS namespace used for service to service calls."
  type        = string
  default     = "movie-search.internal"
}

variable "embedding_model_id" {
  description = "Model the embedding service loads."
  type        = string
  default     = "BAAI/bge-base-en-v1.5"
}

variable "embedding_dimension" {
  description = "Vector width. It must match the `vector(n)` column in the schema."
  type        = number
  default     = 768
}

variable "embedding_query_prefix" {
  description = "Instruction placed in front of a search query. BGE models expect one; the stored documents get none."
  type        = string
  default     = "Represent this sentence for searching relevant passages:"
}

variable "auth_issuer" {
  description = "Issuer claim on the tokens the API mints."
  type        = string
}

variable "auth_audience" {
  description = "Audience claim on the tokens the API mints."
  type        = string
  default     = "movie-search-api"
}

variable "cache_ttl_seconds" {
  description = "How long an identical search stays cached."
  type        = number
  default     = 60
}

variable "rate_limit_per_minute" {
  description = "Requests one client may make per minute."
  type        = number
  default     = 60
}

variable "dotnet_environment" {
  description = "ASPNETCORE_ENVIRONMENT value."
  type        = string
  default     = "Production"
}

variable "log_level" {
  description = "Log level for the Python services."
  type        = string
  default     = "INFO"
}

# --- sizing ------------------------------------------------------------------

variable "api_cpu" {
  description = "CPU units for one API task. 1024 is one vCPU."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory in mebibytes for one API task."
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

variable "api_cpu_target" {
  description = "Average CPU percentage the API scales to hold."
  type        = number
  default     = 60
}

variable "api_memory_target" {
  description = "Average memory percentage the API scales to hold."
  type        = number
  default     = 70
}

variable "mcp_cpu" {
  description = "CPU units for one MCP task."
  type        = number
  default     = 512
}

variable "mcp_memory" {
  description = "Memory in mebibytes for one MCP task."
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

variable "mcp_cpu_target" {
  description = "Average CPU percentage the MCP server scales to hold."
  type        = number
  default     = 60
}

variable "mcp_memory_target" {
  description = "Average memory percentage the MCP server scales to hold."
  type        = number
  default     = 70
}

variable "embeddings_cpu" {
  description = "CPU units for one embedding task. Inference on CPU is the slowest step, so this is the largest allocation."
  type        = number
  default     = 2048
}

variable "embeddings_memory" {
  description = "Memory in mebibytes for one embedding task."
  type        = number
  default     = 4096
}

variable "embeddings_desired_count" {
  description = "Starting number of embedding tasks."
  type        = number
  default     = 1
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

variable "embeddings_cpu_target" {
  description = "Average CPU percentage the embedding service scales to hold."
  type        = number
  default     = 70
}

variable "pipeline_cpu" {
  description = "CPU units for the pipeline task."
  type        = number
  default     = 1024
}

variable "pipeline_memory" {
  description = "Memory in mebibytes for the pipeline task."
  type        = number
  default     = 2048
}

# --- cluster settings --------------------------------------------------------

variable "container_insights" {
  description = "Turn on Container Insights. The autoscaling policies read the metrics it publishes."
  type        = bool
  default     = true
}

variable "baseline_on_demand_tasks" {
  description = "Tasks always placed on on-demand Fargate before any Spot capacity is used."
  type        = number
  default     = 1
}

variable "spot_weight" {
  description = "Weight of Fargate Spot in the capacity provider strategy. Zero uses on-demand only."
  type        = number
  default     = 0
}

variable "enable_execute_command" {
  description = "Allow a shell into a running task with `aws ecs execute-command`."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "Retention of the CloudWatch log groups, in days."
  type        = number
  default     = 30
}

variable "logs_kms_key_arn" {
  description = "Customer managed KMS key for the log groups. Null uses the default CloudWatch encryption."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
