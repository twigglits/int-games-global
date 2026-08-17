output "endpoint" {
  description = "Host and port of the instance."
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "Host name of the instance."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "Port of the instance."
  value       = aws_db_instance.this.port
}

output "database_name" {
  description = "Name of the application database."
  value       = aws_db_instance.this.db_name
}

output "identifier" {
  description = "Instance identifier."
  value       = aws_db_instance.this.identifier
}

output "arn" {
  description = "Instance ARN."
  value       = aws_db_instance.this.arn
}
