/**
 * CloudWatch and X-Ray.
 *
 * In Docker Compose the observability stack is Prometheus, Grafana and Jaeger.
 * In AWS the same three signals are served by managed services, because running
 * a Prometheus and a Jaeger of one's own in production means operating two more
 * stateful systems:
 *
 *   metrics — CloudWatch, from Container Insights and from the EMF exporter in
 *             the OpenTelemetry sidecar.
 *   traces  — X-Ray, from the same sidecar.
 *   logs    — CloudWatch Logs, from the awslogs driver.
 *
 * The application code is unchanged between the two. It exports OTLP to
 * localhost either way.
 */

data "aws_region" "current" {}

# --- X-Ray -------------------------------------------------------------------

resource "aws_xray_sampling_rule" "api" {
  rule_name = "${var.name_prefix}-api"
  priority  = 1000
  version   = 1

  # One trace per second is always kept, plus a percentage of the rest. That
  # keeps a low-traffic environment traceable at all, and keeps a busy one from
  # tracing everything.
  reservoir_size = var.trace_reservoir_size
  fixed_rate     = var.trace_sample_rate

  service_name = "movie-search-api"
  service_type = "*"
  host         = "*"
  http_method  = "*"
  url_path     = "*"
  resource_arn = "*"

  tags = var.tags
}

resource "aws_xray_sampling_rule" "health_checks" {
  rule_name = "${var.name_prefix}-health"
  priority  = 100 # evaluated before the rule above
  version   = 1

  # A health check is polled several times a minute for ever. Tracing it would
  # bury the traces that matter.
  reservoir_size = 0
  fixed_rate     = 0

  service_name = "*"
  service_type = "*"
  host         = "*"
  http_method  = "GET"
  url_path     = "/health*"
  resource_arn = "*"

  tags = var.tags
}

# --- alarms ------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  count = var.create_sns_topic ? 1 : 0

  name              = "${var.name_prefix}-alerts"
  kms_master_key_id = var.sns_kms_key_id
  tags              = var.tags
}

locals {
  alarm_targets = var.create_sns_topic ? [aws_sns_topic.alerts[0].arn] : var.alarm_action_arns
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx"
  alarm_description   = "The API is returning server errors through the load balancer."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.error_count_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_targets
  ok_actions    = local.alarm_targets
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name        = "${var.name_prefix}-api-latency-p95"
  alarm_description = "The API is over its 500 ms p95 budget."
  namespace         = "AWS/ApplicationELB"
  metric_name       = "TargetResponseTime"
  # The requirement is stated at p95, so the alarm reads p95 and not an average.
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.latency_p95_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_targets
  ok_actions    = local.alarm_targets
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.name_prefix}-api-unhealthy-hosts"
  alarm_description   = "One or more API tasks are failing the load balancer health check."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_targets
  ok_actions    = local.alarm_targets
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${var.name_prefix}-rds-cpu"
  alarm_description   = "The database is running hot."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = { DBInstanceIdentifier = var.database_identifier }

  alarm_actions = local.alarm_targets
  ok_actions    = local.alarm_targets
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${var.name_prefix}-rds-free-storage"
  alarm_description   = "The database is running out of storage."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.free_storage_threshold_bytes
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = { DBInstanceIdentifier = var.database_identifier }

  alarm_actions = local.alarm_targets
  ok_actions    = local.alarm_targets
  tags          = var.tags
}

# --- dashboard ---------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "${var.name_prefix}-platform"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Request rate and errors"
          region = data.aws_region.current.region
          view   = "timeSeries"
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, { label = "requests" }],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", { label = "5xx", color = "#d62728" }],
            [".", "HTTPCode_Target_4XX_Count", ".", ".", { label = "4xx", color = "#ff7f0e" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Latency"
          region = data.aws_region.current.region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50", label = "p50" }],
            ["...", { stat = "p95", label = "p95" }],
            ["...", { stat = "p99", label = "p99" }],
          ]
          annotations = {
            horizontal = [{ label = "500 ms budget", value = 0.5, color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "ECS service utilisation"
          region = data.aws_region.current.region
          view   = "timeSeries"
          stat   = "Average"
          period = 60
          metrics = [
            for service in ["api", "mcp-server", "embeddings"] :
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", service, { label = "${service} cpu" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Database"
          region = data.aws_region.current.region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.database_identifier, { stat = "Average", label = "cpu %" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Average", label = "connections" }],
            [".", "ReadLatency", ".", ".", { stat = "Average", label = "read latency" }],
          ]
        }
      },
      {
        type = "log", x = 0, y = 12, width = 24, height = 6
        properties = {
          title  = "API errors"
          region = data.aws_region.current.region
          query  = "SOURCE '/ecs/${var.name_prefix}/api' | fields @timestamp, @message | filter @message like /\"@l\":\"Error\"/ | sort @timestamp desc | limit 50"
        }
      },
    ]
  })
}
