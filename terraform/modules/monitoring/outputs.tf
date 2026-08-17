output "dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.this.dashboard_name
}

output "alerts_topic_arn" {
  description = "SNS topic the alarms publish to, or null when none was created."
  value       = try(aws_sns_topic.alerts[0].arn, null)
}

output "alarm_names" {
  description = "Every alarm this module creates."
  value = [
    aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
    aws_cloudwatch_metric_alarm.api_latency.alarm_name,
    aws_cloudwatch_metric_alarm.unhealthy_hosts.alarm_name,
    aws_cloudwatch_metric_alarm.database_cpu.alarm_name,
    aws_cloudwatch_metric_alarm.database_storage.alarm_name,
  ]
}
