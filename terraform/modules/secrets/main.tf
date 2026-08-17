/**
 * The configuration and secret contract for one environment.
 *
 * This module reads. It creates nothing. Every value it exposes is written
 * before the first `terraform apply`, by `scripts/bootstrap_parameters.sh`.
 *
 * Two stores, split by what the value is
 * --------------------------------------
 * A secret and a hostname want different things from their store, so they get
 * different stores.
 *
 *   Secrets Manager   the four secrets. Rotation with a Lambda, a resource
 *                     policy per secret, cross-account sharing, and a staged
 *                     `AWSCURRENT`/`AWSPREVIOUS` label so a rotation does not
 *                     break tasks mid-flight. Costs $0.40 per secret per month.
 *   Parameter Store   the configuration. Domain name, hosted zone, certificate
 *                     ARN, alarm topic ARN. None of these is secret, none needs
 *                     rotation, and the standard tier is free.
 *
 * Why no secret reaches the state file
 * ------------------------------------
 * Choosing Secrets Manager does not by itself keep secrets out of state — a
 * `data "aws_secretsmanager_secret_version"` would persist the value, exactly
 * as `random_password` did. Three separate mechanisms prevent it:
 *
 *   * `data "aws_secretsmanager_secret"` (singular, no `_version`) returns the
 *     ARN, the KMS key and the tags. It does not return the value. This is what
 *     resolves the ARN, which cannot be constructed by hand because Secrets
 *     Manager appends six random characters to every one.
 *   * The three application secrets are needed only by the ECS agent, which
 *     reads them itself at task start from the ARN in the task definition.
 *     Terraform never holds them.
 *   * The database password is the one value Terraform must hand to a resource.
 *     An `ephemeral` resource reads it in the RDS module and passes it to the
 *     write-only `password_wo` argument. Neither is persisted.
 *
 * CI enforces this: `.github/workflows/ci.yml` fails the build if a
 * `data "aws_secretsmanager_secret_version"`, a `data "aws_ssm_parameter"` or a
 * secret-writing resource ever appears in this directory.
 *
 * The two trees
 * -------------
 *   Parameter Store (String)
 *     /<project>/<environment>/config/domain-name                required
 *     /<project>/<environment>/config/route53-zone-id            optional
 *     /<project>/<environment>/config/certificate-arn            optional
 *     /<project>/<environment>/config/github-oidc-provider-arn   optional
 *     /<project>/<environment>/config/alarm-topic-arn            optional
 *     /<project>/<environment>/config/alb-access-logs-bucket     optional
 *
 *   Secrets Manager
 *     <project>/<environment>/database-password
 *     <project>/<environment>/jwt-signing-key
 *     <project>/<environment>/clients/<client-id>
 */

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  root        = "/${var.project}/${var.environment}"
  config_path = "${local.root}/config"

  # Secrets Manager names carry no leading slash, by convention and because the
  # console renders the tree from the slashes that are there.
  secret_prefix = "${var.project}/${var.environment}"
}

# --- secrets -------------------------------------------------------------------
# The ARN is resolved, not constructed. Secrets Manager appends six random
# characters to the ARN of every secret it creates, so `...:secret:name` cannot
# be assembled from the account, region and name the way an SSM parameter ARN
# can.
#
# This is the singular data source. It returns metadata only — arn, kms_key_id,
# tags, rotation settings. Reading a value needs `aws_secretsmanager_secret_version`,
# which nothing here uses and CI refuses to let anything add.

data "aws_secretsmanager_secret" "database_password" {
  name = "${local.secret_prefix}/database-password"
}

data "aws_secretsmanager_secret" "jwt_signing_key" {
  name = "${local.secret_prefix}/jwt-signing-key"
}

data "aws_secretsmanager_secret" "client" {
  for_each = toset(var.api_client_ids)
  name     = "${local.secret_prefix}/clients/${each.value}"
}

locals {
  secret_arns = {
    database_password = data.aws_secretsmanager_secret.database_password.arn
    jwt_signing_key   = data.aws_secretsmanager_secret.jwt_signing_key.arn
  }

  client_secret_arns = { for id, secret in data.aws_secretsmanager_secret.client : id => secret.arn }

  # Every secret the ECS task execution role is allowed to read.
  readable_secret_arns = concat(
    values(local.secret_arns),
    values(local.client_secret_arns),
  )

  # The config subtree, for the deployment role. A prefix, because Terraform
  # reads the whole path rather than named parameters.
  config_parameter_arns = [
    "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${local.config_path}/*",
  ]
}

# --- configuration -----------------------------------------------------------
# One call reads the whole config subtree. A parameter that is absent is simply
# missing from the result, so an optional value needs no `count` and cannot fail
# the plan. `with_decryption` is false because nothing under `config/` is secret.

data "aws_ssm_parameters_by_path" "config" {
  path            = local.config_path
  recursive       = false
  with_decryption = false

  lifecycle {
    postcondition {
      condition = alltrue([
        for required in var.required_config_keys :
        contains([for name in self.names : basename(name)], required)
      ])
      error_message = <<-EOT
        Required configuration is missing from Parameter Store under ${local.config_path}.

        Expected every one of: ${join(", ", var.required_config_keys)}

        Run the bootstrap script once for this environment:
          ./scripts/bootstrap_parameters.sh ${var.environment}
      EOT
    }
  }
}

locals {
  # `aws_ssm_parameters_by_path` marks every returned value sensitive, because in
  # general a parameter can be a secret. This subtree is not: it is read with
  # `with_decryption = false`, and nothing under `config/` is a SecureString. The
  # values are therefore unmarked here, which is what allows a hosted zone id to
  # be used as a `for_each` key and a domain name to appear in an output.
  #
  # Nothing under `secrets/` passes through this path. Those are never read.
  config = zipmap(
    [for name in data.aws_ssm_parameters_by_path.config.names : basename(name)],
    nonsensitive(data.aws_ssm_parameters_by_path.config.values),
  )

  # A bootstrap run writes "-" for an optional value that was left unset, so the
  # parameter tree is a complete, readable contract rather than a set of holes.
  config_or_null = {
    for key, value in local.config :
    key => trimspace(value) == "" || trimspace(value) == "-" ? null : value
  }
}
