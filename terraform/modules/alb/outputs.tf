output "dns_name" {
  description = "DNS name of the load balancer."
  value       = aws_lb.this.dns_name
}

output "zone_id" {
  description = "Hosted zone of the load balancer, for an alias record."
  value       = aws_lb.this.zone_id
}

output "arn" {
  description = "Load balancer ARN."
  value       = aws_lb.this.arn
}

output "arn_suffix" {
  description = "Suffix used by CloudWatch metric dimensions."
  value       = aws_lb.this.arn_suffix
}

output "target_group_arn" {
  description = "Target group the API service registers with."
  value       = aws_lb_target_group.api.arn
}

output "target_group_arn_suffix" {
  description = "Target group suffix used by CloudWatch metric dimensions."
  value       = aws_lb_target_group.api.arn_suffix
}

output "https_listener_arn" {
  description = "HTTPS listener ARN."
  value       = aws_lb_listener.https.arn
}

output "certificate_arn" {
  description = "Certificate the HTTPS listener uses."
  value       = local.certificate_arn
}

output "api_url" {
  description = "Public base URL of the API."
  value       = "https://${var.domain_name}"
}
