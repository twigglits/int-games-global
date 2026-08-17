/**
 * Development environment.
 *
 * It differs from production in the places where cost matters more than
 * resilience, and every one of those differences is a variable rather than a
 * fork of the code:
 *
 *   * one NAT gateway instead of one per availability zone,
 *   * a single-AZ database with a short backup retention,
 *   * no deletion protection, so the environment can be torn down,
 *   * `aws ecs execute-command` allowed, so a task can be inspected,
 *   * a smaller task count and smaller tasks.
 */

terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives in S3, locked through DynamoDB. Both are created once, outside
  # this configuration; see terraform/README.md for the bootstrap commands.
  backend "s3" {
    bucket         = "movie-search-tfstate-8aaa33ad"
    key            = "dev/terraform.tfstate"
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
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

module "platform" {
  source = "../../"

  project     = "movie-search"
  environment = "dev"
  region      = var.region
  owner       = var.owner
  cost_centre = var.cost_centre

  # --- networking: one NAT gateway is enough for a development environment ---
  vpc_cidr                   = "10.20.0.0/16"
  availability_zone_count    = 2
  single_nat_gateway         = true
  enable_interface_endpoints = false

  # The domain, certificate, hosted zone, alarm topic and access log bucket
  # are read from Parameter Store. See modules/secrets.

  # --- database: single AZ, short retention -----------------------------------
  database_instance_class        = "db.t4g.medium"
  database_allocated_storage     = 20
  database_max_allocated_storage = 100
  database_multi_az              = false
  database_backup_retention_days = 1

  # --- application ------------------------------------------------------------
  image_tag            = var.image_tag
  force_destroy        = var.force_destroy
  image_tag_mutability = "MUTABLE" # a dev tag is overwritten on every push
  mcp_transport        = "http"

  # --- sizing: two of each, so a rolling deployment is still observable -------
  api_cpu                 = 512
  api_memory              = 1024
  api_desired_count       = 1
  api_min_capacity        = 1
  api_max_capacity        = 4
  mcp_cpu                 = 512
  mcp_memory              = 1024
  mcp_desired_count       = 1
  mcp_min_capacity        = 1
  mcp_max_capacity        = 3
  embeddings_cpu          = 2048
  embeddings_memory       = 4096
  embeddings_min_capacity = 1
  embeddings_max_capacity = 2
  spot_weight             = 1 # dev tolerates a Spot interruption

  # --- operations --------------------------------------------------------------
  enable_execute_command = true
  log_retention_days     = 7
  trace_sample_rate      = 1.0 # trace everything: dev traffic is tiny

  github_subject_patterns = var.github_subject_patterns
}
