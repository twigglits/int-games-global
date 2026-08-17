/**
 * Production environment.
 *
 * Everything that development trades away for cost is restored here: a NAT
 * gateway per availability zone, a Multi-AZ database, deletion protection on
 * both the database and the load balancer, immutable image tags, no shell into
 * a running task, and on-demand capacity only.
 */

terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket         = "movie-search-tfstate-8aaa33ad"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "movie-search-tfstate-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "movie-search"
      Environment = "prod"
      ManagedBy   = "terraform"
    }
  }
}

module "platform" {
  source = "../../"

  project     = "movie-search"
  environment = "prod"
  region      = var.region
  owner       = var.owner
  cost_centre = var.cost_centre

  # --- networking: no shared single point of failure --------------------------
  vpc_cidr                   = "10.30.0.0/16"
  availability_zone_count    = 3
  single_nat_gateway         = false
  enable_interface_endpoints = true

  # The domain, certificate, hosted zone, alarm topic and access log bucket
  # are read from Parameter Store. See modules/secrets.

  # --- database: Multi-AZ, a month of backups ------------------------------------
  database_instance_class        = "db.r7g.large"
  database_allocated_storage     = 100
  database_max_allocated_storage = 500
  database_multi_az              = true
  database_backup_retention_days = 30

  # --- application -----------------------------------------------------------------
  # The tag is always an explicit commit SHA. `latest` in production means
  # nobody can say which code is running.
  image_tag            = var.image_tag
  force_destroy        = var.force_destroy
  image_tag_mutability = "IMMUTABLE"
  mcp_transport        = "http"

  # --- sizing -------------------------------------------------------------------------
  api_cpu                 = 1024
  api_memory              = 2048
  api_desired_count       = 3
  api_min_capacity        = 3
  api_max_capacity        = 20
  mcp_cpu                 = 1024
  mcp_memory              = 2048
  mcp_desired_count       = 3
  mcp_min_capacity        = 3
  mcp_max_capacity        = 12
  embeddings_cpu          = 4096
  embeddings_memory       = 8192
  embeddings_min_capacity = 2
  embeddings_max_capacity = 8
  spot_weight             = 0 # on-demand only

  # --- operations ------------------------------------------------------------------------
  enable_execute_command = false
  log_retention_days     = 90
  trace_sample_rate      = 0.1

  github_subject_patterns = var.github_subject_patterns
}
