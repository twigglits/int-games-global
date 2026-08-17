output "vpc_id" {
  description = "Identifier of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnets. The load balancer and the NAT gateways live here."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnets. The ECS tasks live here."
  value       = aws_subnet.private[*].id
}

output "database_subnet_ids" {
  description = "Database subnets. They have no route to the internet."
  value       = aws_subnet.database[*].id
}

output "alb_security_group_id" {
  description = "Security group of the load balancer."
  value       = aws_security_group.alb.id
}

output "tasks_security_group_id" {
  description = "Security group shared by the ECS tasks."
  value       = aws_security_group.tasks.id
}

output "database_security_group_id" {
  description = "Security group of the RDS instance."
  value       = aws_security_group.database.id
}

output "availability_zones" {
  description = "Availability zones in use."
  value       = local.azs
}

output "flow_log_group_name" {
  description = "CloudWatch log group that receives the VPC flow logs."
  value       = aws_cloudwatch_log_group.flow_logs.name
}
