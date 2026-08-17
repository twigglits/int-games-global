/**
 * ECS on Fargate.
 *
 * Three long-running services and one batch task:
 *
 *   api         — public, behind the load balancer.
 *   mcp-server  — private, found through Cloud Map at mcp-server.<namespace>.
 *   embeddings  — private, found through Cloud Map at embeddings.<namespace>.
 *   pipeline    — a task definition with no service. It is started on demand
 *                 with `aws ecs run-task`, or on a schedule by EventBridge.
 *
 * Every task runs in a private subnet with no public IP. Outbound traffic goes
 * through NAT, and inbound traffic reaches only the API, only from the load
 * balancer, only on its own port.
 *
 * Why ECS and not EKS: see ECS_EKS_CHOICE.md at the repository root.
 */

data "aws_region" "current" {}

locals {
  # The API is the only service that needs a load balancer attachment.
  log_group_prefix = "/ecs/${var.name_prefix}"

  common_environment = [
    { name = "ASPNETCORE_ENVIRONMENT", value = var.dotnet_environment },
    { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
    { name = "OTEL_EXPORTER_OTLP_PROTOCOL", value = "http/protobuf" },
  ]
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"

  setting {
    # Container Insights is what turns per-task CPU and memory into CloudWatch
    # metrics. Without it the autoscaling policies below have nothing to read.
    name  = "containerInsights"
    value = var.container_insights ? "enhanced" : "disabled"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cluster" })
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = var.baseline_on_demand_tasks
  }

  dynamic "default_capacity_provider_strategy" {
    for_each = var.spot_weight > 0 ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = var.spot_weight
    }
  }
}

# --- service discovery -------------------------------------------------------
# The API resolves the MCP server by name, and the MCP server resolves the
# embedding service by name. A private DNS namespace means neither needs a load
# balancer, and neither is reachable from outside the VPC.

resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = var.service_discovery_namespace
  description = "Internal service discovery for the movie search platform."
  vpc         = var.vpc_id
  tags        = var.tags
}

resource "aws_service_discovery_service" "internal" {
  for_each = toset(["mcp-server", "embeddings"])

  name = each.value

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 15
      type = "A"
    }
  }

  # ECS reports task health to Cloud Map itself, so no health check of its own
  # is configured here.
  health_check_custom_config {}

  tags = var.tags
}

# --- log groups --------------------------------------------------------------

resource "aws_cloudwatch_log_group" "service" {
  for_each = toset(["api", "mcp-server", "embeddings", "pipeline"])

  name              = "${local.log_group_prefix}/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
  tags              = merge(var.tags, { Service = each.value })
}

# --- embedding service -------------------------------------------------------
# Text Embeddings Inference. The model is downloaded on first start; a warm
# start reads it from the EFS-free local task storage, so the start period on
# the health check is generous.

resource "aws_ecs_task_definition" "embeddings" {
  family                   = "${var.name_prefix}-embeddings"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.embeddings_cpu
  memory                   = var.embeddings_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "embeddings"
      image     = var.embeddings_image
      essential = true
      command   = ["--model-id=${var.embedding_model_id}", "--auto-truncate", "--port=80"]

      portMappings = [{ containerPort = 80, protocol = "tcp", name = "http" }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.service["embeddings"].name
          "awslogs-region"        = data.aws_region.current.region
          "awslogs-stream-prefix" = "embeddings"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:80/health || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 10
        startPeriod = 180
      }
    },
  ])

  tags = merge(var.tags, { Service = "embeddings" })
}

resource "aws_ecs_service" "embeddings" {
  name            = "embeddings"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.embeddings.arn
  desired_count   = var.embeddings_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.internal["embeddings"].arn
  }

  enable_execute_command = var.enable_execute_command
  propagate_tags         = "SERVICE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(var.tags, { Service = "embeddings" })

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# --- MCP server --------------------------------------------------------------

resource "aws_ecs_task_definition" "mcp_server" {
  family                   = "${var.name_prefix}-mcp-server"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.mcp_cpu
  memory                   = var.mcp_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "mcp-server"
      image     = var.mcp_image
      essential = true

      portMappings = [{ containerPort = 8000, protocol = "tcp", name = "http" }]

      environment = [
        { name = "MCP_HOST", value = "0.0.0.0" },
        { name = "MCP_PORT", value = "8000" },
        # Streamable HTTP in production. A long-lived SSE stream survives a load
        # balancer idle timeout poorly, and a request-scoped exchange makes the
        # trace context propagate cleanly.
        { name = "MCP_TRANSPORT", value = var.mcp_transport },
        { name = "MCP_LOG_LEVEL", value = var.log_level },
        { name = "POSTGRES_HOST", value = var.database_host },
        { name = "POSTGRES_PORT", value = tostring(var.database_port) },
        { name = "POSTGRES_DB", value = var.database_name },
        # The user name is not a secret and Parameter Store has no equivalent of
        # the Secrets Manager JSON-key extraction, so it stays a plain variable
        # and only the password is injected from Secrets Manager.
        { name = "POSTGRES_USER", value = var.database_username },
        { name = "EMBEDDINGS_URL", value = "http://embeddings.${var.service_discovery_namespace}:80" },
        { name = "EMBEDDING_DIM", value = tostring(var.embedding_dimension) },
        { name = "EMBEDDING_QUERY_PREFIX", value = var.embedding_query_prefix },
        { name = "MCP_DB_POOL_MIN", value = "2" },
        { name = "MCP_DB_POOL_MAX", value = "20" },
        { name = "SERVICE_NAME", value = "movie-search-mcp" },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
      ]

      # Injected by the ECS agent from Parameter Store at task start. Terraform
      # holds the ARN and never the value, so nothing here reaches the state
      # file, the plan file or the console.
      secrets = [
        { name = "POSTGRES_PASSWORD", valueFrom = var.database_password_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.service["mcp-server"].name
          "awslogs-region"        = data.aws_region.current.region
          "awslogs-stream-prefix" = "mcp"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:8000/health || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 5
        startPeriod = 60
      }

      dependsOn = [{ containerName = "otel-collector", condition = "START" }]
    },
    local.otel_sidecar,
  ])

  tags = merge(var.tags, { Service = "mcp-server" })
}

resource "aws_ecs_service" "mcp_server" {
  name            = "mcp-server"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.mcp_server.arn
  desired_count   = var.mcp_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.internal["mcp-server"].arn
  }

  enable_execute_command = var.enable_execute_command
  propagate_tags         = "SERVICE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(var.tags, { Service = "mcp-server" })

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# --- .NET API ----------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image
      essential = true

      portMappings = [{ containerPort = var.api_container_port, protocol = "tcp", name = "http" }]

      environment = concat(local.common_environment, [
        { name = "ASPNETCORE_URLS", value = "http://+:${var.api_container_port}" },
        { name = "Logging__Directory", value = "/app/logs" },
        { name = "Mcp__ServerUrl", value = "http://mcp-server.${var.service_discovery_namespace}:8000" },
        { name = "Mcp__Transport", value = var.mcp_transport },
        { name = "Mcp__RequestTimeoutSeconds", value = "30" },
        { name = "Cache__Enabled", value = "true" },
        { name = "Cache__TtlSeconds", value = tostring(var.cache_ttl_seconds) },
        { name = "RequestLimits__PermitsPerWindow", value = tostring(var.rate_limit_per_minute) },
        { name = "RequestLimits__WindowSeconds", value = "60" },
        { name = "Auth__Issuer", value = var.auth_issuer },
        { name = "Auth__Audience", value = var.auth_audience },
        { name = "Auth__AccessTokenLifetimeMinutes", value = "60" },
        { name = "Auth__Clients__0__ClientId", value = var.reader_client_id },
        { name = "Auth__Clients__0__Roles__0", value = "reader" },
        { name = "Auth__Clients__1__ClientId", value = var.admin_client_id },
        { name = "Auth__Clients__1__Roles__0", value = "reader" },
        { name = "Auth__Clients__1__Roles__1", value = "admin" },
        { name = "OTEL_SERVICE_NAME", value = "movie-search-api" },
      ])

      secrets = [
        { name = "Auth__SigningKey", valueFrom = var.jwt_signing_key_secret_arn },
        { name = "Auth__Clients__0__ClientSecret", valueFrom = var.reader_client_secret_arn },
        { name = "Auth__Clients__1__ClientSecret", valueFrom = var.admin_client_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.service["api"].name
          "awslogs-region"        = data.aws_region.current.region
          "awslogs-stream-prefix" = "api"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:${var.api_container_port}/health/live || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 5
        startPeriod = 60
      }

      dependsOn = [{ containerName = "otel-collector", condition = "START" }]
    },
    local.otel_sidecar,
  ])

  tags = merge(var.tags, { Service = "api" })
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  # A new task must pass the load balancer health check before the old one is
  # drained, and a deployment that never becomes healthy is rolled back rather
  # than left half applied.
  health_check_grace_period_seconds = 90

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.api_target_group_arn
    container_name   = "api"
    container_port   = var.api_container_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  enable_execute_command = var.enable_execute_command
  propagate_tags         = "SERVICE"

  tags = merge(var.tags, { Service = "api" })

  depends_on = [aws_ecs_service.mcp_server]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# --- data pipeline task ------------------------------------------------------
# No service: the pipeline runs, writes and exits. It is started by the delivery
# workflow after a deployment, and on a schedule when the dataset is refreshed.

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.name_prefix}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.pipeline_cpu
  memory                   = var.pipeline_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "pipeline"
      image     = var.pipeline_image
      essential = true

      environment = [
        { name = "POSTGRES_HOST", value = var.database_host },
        { name = "POSTGRES_PORT", value = tostring(var.database_port) },
        { name = "POSTGRES_DB", value = var.database_name },
        # The user name is not a secret and Parameter Store has no equivalent of
        # the Secrets Manager JSON-key extraction, so it stays a plain variable
        # and only the password is injected from Secrets Manager.
        { name = "POSTGRES_USER", value = var.database_username },
        { name = "EMBEDDINGS_URL", value = "http://embeddings.${var.service_discovery_namespace}:80" },
        { name = "EMBEDDING_DIM", value = tostring(var.embedding_dimension) },
        { name = "EMBEDDING_QUERY_PREFIX", value = var.embedding_query_prefix },
        { name = "PIPELINE_BATCH_SIZE", value = "32" },
        { name = "PIPELINE_LOG_LEVEL", value = var.log_level },
        { name = "PIPELINE_LOG_DIR", value = "/tmp" },
        { name = "PIPELINE_REPORT_DIR", value = "/tmp" },
      ]

      secrets = [
        { name = "POSTGRES_PASSWORD", valueFrom = var.database_password_secret_arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.service["pipeline"].name
          "awslogs-region"        = data.aws_region.current.region
          "awslogs-stream-prefix" = "pipeline"
        }
      }
    },
  ])

  tags = merge(var.tags, { Service = "pipeline" })
}

# --- autoscaling -------------------------------------------------------------
# Target tracking on both CPU and memory. Whichever signal crosses its target
# first adds a task, and a task is only removed when both are comfortable, which
# is what the longer scale-in cooldown expresses.

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_min_capacity
  max_capacity       = var.api_max_capacity

  tags = var.tags
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.name_prefix}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.api_cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "api_memory" {
  name               = "${var.name_prefix}-api-memory"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = var.api_memory_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_target" "mcp" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.mcp_server.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.mcp_min_capacity
  max_capacity       = var.mcp_max_capacity

  tags = var.tags
}

resource "aws_appautoscaling_policy" "mcp_cpu" {
  name               = "${var.name_prefix}-mcp-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.mcp.service_namespace
  resource_id        = aws_appautoscaling_target.mcp.resource_id
  scalable_dimension = aws_appautoscaling_target.mcp.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.mcp_cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "mcp_memory" {
  name               = "${var.name_prefix}-mcp-memory"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.mcp.service_namespace
  resource_id        = aws_appautoscaling_target.mcp.resource_id
  scalable_dimension = aws_appautoscaling_target.mcp.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = var.mcp_memory_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Embedding inference on CPU is the slowest part of the platform, so it scales
# on CPU alone; memory stays flat once the model is loaded.
resource "aws_appautoscaling_target" "embeddings" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.embeddings.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.embeddings_min_capacity
  max_capacity       = var.embeddings_max_capacity

  tags = var.tags
}

resource "aws_appautoscaling_policy" "embeddings_cpu" {
  name               = "${var.name_prefix}-embeddings-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.embeddings.service_namespace
  resource_id        = aws_appautoscaling_target.embeddings.resource_id
  scalable_dimension = aws_appautoscaling_target.embeddings.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = var.embeddings_cpu_target
    # A new embedding task has to download and load the model, so it is slow to
    # arrive and expensive to discard. Both cooldowns are long.
    scale_in_cooldown  = 600
    scale_out_cooldown = 180
  }
}
