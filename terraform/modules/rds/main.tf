/**
 * RDS PostgreSQL with pgvector.
 *
 * pgvector needs no special instance setting. It ships with the RDS PostgreSQL
 * engine as an available extension, and the Flyway migration turns it on with
 * `CREATE EXTENSION vector`. The parameter group below therefore configures the
 * things that do need configuring for a vector workload.
 *
 * The instance sits in the database subnets, which have no route to a NAT
 * gateway, and its security group accepts traffic only from the ECS task
 * security group. There is no public endpoint.
 *
 * The master password never enters the Terraform state file. It is read from
 * Secrets Manager by an `ephemeral` resource, whose value Terraform holds in
 * memory for the length of the operation and never persists, and it is handed
 * to `password_wo`, a write-only argument that is likewise absent from both the
 * plan and the state. Rotating it is a `put-secret-value` followed by an
 * increment of `database_password_version`.
 */

# Ephemeral: fetched during the operation, never written to state or to a plan
# file. This is the only place in the configuration that reads a secret value.
#
# The data source of the same name would persist it. `ephemeral` is the whole
# difference, and CI greps for the data source to keep it that way.
ephemeral "aws_secretsmanager_secret_version" "master_password" {
  secret_id = var.database_password_secret_arn
}

resource "aws_db_subnet_group" "this" {
  name        = "${var.name_prefix}-db"
  description = "Private database subnets for the movie search platform."
  subnet_ids  = var.subnet_ids
  tags        = merge(var.tags, { Name = "${var.name_prefix}-db" })
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 tuned for a pgvector workload."

  # An HNSW index is read almost entirely from memory. A larger cache is the
  # single setting that most affects vector search latency.
  parameter {
    name         = "shared_buffers"
    value        = "{DBInstanceClassMemory/32768}"
    apply_method = "pending-reboot"
  }

  # Building an HNSW index is memory hungry. pgvector recommends a maintenance
  # work memory larger than the index, so that the build stays in memory.
  parameter {
    name         = "maintenance_work_mem"
    value        = "1048576" # 1 GiB, in kilobytes
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "work_mem"
    value = "32768" # 32 MiB per sort or hash node
  }

  # Log any statement slower than a second, so a slow vector query is visible
  # without turning on full statement logging.
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  # pg_stat_statements is what makes "which query is slow" answerable at all.
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = var.tags
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name  = var.database_name
  username = var.database_username
  port     = 5432

  # Write-only: the value is sent to the API and then discarded. It appears in
  # neither the plan file nor the state file. `password_wo_version` is what
  # Terraform stores instead, and incrementing it is what triggers a change.
  password_wo         = ephemeral.aws_secretsmanager_secret_version.master_password.secret_string
  password_wo_version = var.database_password_version

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  parameter_group_name = aws_db_parameter_group.this.name

  backup_retention_period   = var.backup_retention_days
  backup_window             = var.backup_window
  maintenance_window        = var.maintenance_window
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-final-${var.environment}"

  auto_minor_version_upgrade = true
  apply_immediately          = var.apply_immediately

  performance_insights_enabled          = var.performance_insights_enabled
  performance_insights_retention_period = var.performance_insights_enabled ? 7 : null
  monitoring_interval                   = var.enhanced_monitoring_interval
  monitoring_role_arn                   = var.enhanced_monitoring_interval == 0 ? null : aws_iam_role.monitoring[0].arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = merge(var.tags, { Name = "${var.name_prefix}-postgres" })
}

# --- enhanced monitoring role ------------------------------------------------

data "aws_iam_policy_document" "monitoring_assume" {
  count = var.enhanced_monitoring_interval == 0 ? 0 : 1

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "monitoring" {
  count = var.enhanced_monitoring_interval == 0 ? 0 : 1

  name               = "${var.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.monitoring_assume[0].json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "monitoring" {
  count = var.enhanced_monitoring_interval == 0 ? 0 : 1

  role       = aws_iam_role.monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
