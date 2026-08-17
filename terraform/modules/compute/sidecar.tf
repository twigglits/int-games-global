/**
 * The AWS Distro for OpenTelemetry collector, run as a sidecar.
 *
 * Both application containers export OTLP to `localhost:4318`, exactly as they
 * do against Jaeger in Docker Compose. The sidecar receives those spans and
 * forwards them to X-Ray. Nothing in the application code changes between the
 * two environments; only the endpoint behind localhost does.
 */

locals {
  otel_sidecar = {
    name      = "otel-collector"
    image     = var.otel_collector_image
    essential = false

    # The bundled configuration receives OTLP and exports to X-Ray and to
    # CloudWatch EMF, so no configuration file has to be mounted.
    command = ["--config=/etc/ecs/ecs-default-config.yaml"]

    portMappings = [
      { containerPort = 4317, protocol = "tcp" },
      { containerPort = 4318, protocol = "tcp" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.otel.name
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = "otel"
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "otel" {
  name              = "${local.log_group_prefix}/otel-collector"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
  tags              = merge(var.tags, { Service = "otel-collector" })
}
