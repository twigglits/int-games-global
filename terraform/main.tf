/**
 * The movie search platform, as one composable module.
 *
 * This root declares no provider and no backend, so it can be called from
 * `environments/dev` and `environments/prod` with different settings and
 * different state. Each environment supplies the provider, the backend and its
 * own variable values.
 *
 * Order of creation, which Terraform derives from the references below:
 *
 *   secrets ─▶ networking ─▶ iam ─▶ rds ─▶ compute
 *           └─▶ ecr ───────┘     alb ──┘        └─▶ monitoring
 *
 * `secrets` reads both stores: Parameter Store for the configuration, and
 * Secrets Manager for the four secrets. Every configuration value and every
 * secret reference comes from there rather than from a `-var` flag, so
 * `terraform apply` needs no arguments beyond the image tag, and no secret
 * value ever reaches the state file. See modules/secrets/main.tf.
 */

locals {
  name_prefix = "${var.project}-${var.environment}"

  # Applied to every resource in every module. Three of these are required by
  # the brief; `Owner` and `CostCentre` make an unexplained bill answerable.
  common_tags = merge(
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = var.repository_url
    },
    var.owner == null ? {} : { Owner = var.owner },
    var.cost_centre == null ? {} : { CostCentre = var.cost_centre },
    var.extra_tags,
  )

  # Configuration read from Parameter Store. Named here so that every consumer
  # reads one local rather than repeating the module reference.
  domain_name              = module.secrets.domain_name
  github_oidc_provider_arn = module.secrets.github_oidc_provider_arn

  # An image reference is the repository URL plus the tag the workflow pushed.
  api_image      = "${module.ecr.repository_urls["api"]}:${var.image_tag}"
  mcp_image      = "${module.ecr.repository_urls["mcp-server"]}:${var.image_tag}"
  pipeline_image = "${module.ecr.repository_urls["pipeline"]}:${var.image_tag}"
}

module "networking" {
  source = "./modules/networking"

  name_prefix                = local.name_prefix
  region                     = var.region
  vpc_cidr                   = var.vpc_cidr
  availability_zone_count    = var.availability_zone_count
  single_nat_gateway         = var.single_nat_gateway
  enable_interface_endpoints = var.enable_interface_endpoints
  flow_log_retention_days    = var.log_retention_days
  api_container_port         = var.api_container_port
  tags                       = local.common_tags
}

module "ecr" {
  source = "./modules/ecr"

  name_prefix          = local.name_prefix
  repository_names     = ["api", "mcp-server", "pipeline"]
  image_tag_mutability = var.image_tag_mutability
  force_delete         = var.force_destroy || var.environment != "prod"
  tags                 = local.common_tags
}

# Read-only. Creates nothing; both stores are written once per environment by
# scripts/bootstrap_parameters.sh before the first apply.
module "secrets" {
  source = "./modules/secrets"

  project        = var.project
  environment    = var.environment
  api_client_ids = [var.reader_client_id, var.admin_client_id]
}

module "iam" {
  source = "./modules/iam"

  name_prefix              = local.name_prefix
  secret_arns              = module.secrets.readable_secret_arns
  config_parameter_arns    = module.secrets.config_parameter_arns
  ecr_repository_arns      = values(module.ecr.repository_arns)
  enable_execute_command   = var.enable_execute_command
  github_oidc_provider_arn = local.github_oidc_provider_arn
  github_subject_patterns  = var.github_subject_patterns
  tags                     = local.common_tags
}

module "rds" {
  source = "./modules/rds"

  name_prefix       = local.name_prefix
  environment       = var.environment
  subnet_ids        = module.networking.database_subnet_ids
  security_group_id = module.networking.database_security_group_id

  engine_version               = var.database_engine_version
  instance_class               = var.database_instance_class
  allocated_storage            = var.database_allocated_storage
  max_allocated_storage        = var.database_max_allocated_storage
  database_name                = var.database_name
  database_username            = var.database_username
  database_password_secret_arn = module.secrets.database_password_secret_arn
  database_password_version    = var.database_password_version

  multi_az              = var.database_multi_az
  backup_retention_days = var.database_backup_retention_days
  deletion_protection   = var.environment == "prod" && !var.force_destroy
  skip_final_snapshot   = var.force_destroy || var.environment != "prod"
  apply_immediately     = var.environment != "prod"

  tags = local.common_tags
}

module "alb" {
  source = "./modules/alb"

  name_prefix                = local.name_prefix
  vpc_id                     = module.networking.vpc_id
  public_subnet_ids          = module.networking.public_subnet_ids
  security_group_id          = module.networking.alb_security_group_id
  api_container_port         = var.api_container_port
  domain_name                = local.domain_name
  certificate_arn            = module.secrets.certificate_arn
  route53_zone_id            = module.secrets.route53_zone_id
  enable_deletion_protection = var.environment == "prod" && !var.force_destroy
  access_logs_bucket         = module.secrets.alb_access_logs_bucket
  tags                       = local.common_tags
}

module "compute" {
  source = "./modules/compute"

  name_prefix        = local.name_prefix
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.tasks_security_group_id
  execution_role_arn = module.iam.execution_role_arn
  task_role_arn      = module.iam.task_role_arn

  api_image      = local.api_image
  mcp_image      = local.mcp_image
  pipeline_image = local.pipeline_image

  database_host                = module.rds.address
  database_port                = module.rds.port
  database_name                = module.rds.database_name
  database_username            = var.database_username
  database_password_secret_arn = module.secrets.database_password_secret_arn

  jwt_signing_key_secret_arn = module.secrets.jwt_signing_key_secret_arn
  reader_client_id           = var.reader_client_id
  reader_client_secret_arn   = module.secrets.client_secret_arns[var.reader_client_id]
  admin_client_id            = var.admin_client_id
  admin_client_secret_arn    = module.secrets.client_secret_arns[var.admin_client_id]

  api_container_port   = var.api_container_port
  api_target_group_arn = module.alb.target_group_arn
  mcp_transport        = var.mcp_transport
  embedding_model_id   = var.embedding_model_id
  embedding_dimension  = var.embedding_dimension
  auth_issuer          = "https://${local.domain_name}"
  auth_audience        = var.auth_audience
  dotnet_environment   = var.environment == "prod" ? "Production" : "Staging"

  api_cpu                 = var.api_cpu
  api_memory              = var.api_memory
  api_desired_count       = var.api_desired_count
  api_min_capacity        = var.api_min_capacity
  api_max_capacity        = var.api_max_capacity
  mcp_cpu                 = var.mcp_cpu
  mcp_memory              = var.mcp_memory
  mcp_desired_count       = var.mcp_desired_count
  mcp_min_capacity        = var.mcp_min_capacity
  mcp_max_capacity        = var.mcp_max_capacity
  embeddings_cpu          = var.embeddings_cpu
  embeddings_memory       = var.embeddings_memory
  embeddings_min_capacity = var.embeddings_min_capacity
  embeddings_max_capacity = var.embeddings_max_capacity

  enable_execute_command = var.enable_execute_command
  log_retention_days     = var.log_retention_days
  spot_weight            = var.spot_weight

  tags = local.common_tags
}

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix             = local.name_prefix
  cluster_name            = module.compute.cluster_name
  alb_arn_suffix          = module.alb.arn_suffix
  target_group_arn_suffix = module.alb.target_group_arn_suffix
  database_identifier     = module.rds.identifier

  trace_sample_rate = var.trace_sample_rate
  create_sns_topic  = module.secrets.alarm_topic_arn == null
  alarm_action_arns = module.secrets.alarm_topic_arn == null ? [] : [module.secrets.alarm_topic_arn]

  tags = local.common_tags
}
