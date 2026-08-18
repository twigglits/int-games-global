/**
 * IAM roles for the ECS tasks.
 *
 * Two roles per workload, because they are used by two different actors:
 *
 *   execution role — used by the ECS agent, before the container starts. It
 *                    pulls the image, reads the Secrets Manager secrets that
 *                    are injected as environment variables, and creates the log
 *                    stream. Terraform never reads those secrets itself.
 *   task role      — used by the application code once it is running. Here it
 *                    only needs to write X-Ray segments.
 *
 * Splitting them is what keeps the application from being able to read a secret
 * it was not given, or to pull an image it was not assigned.
 *
 * No IAM user and no access key is created anywhere. A task assumes its role
 * through the task metadata endpoint.
 */

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Confused-deputy protection: the role may only be assumed on behalf of a
    # task in this account, in this cluster.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

# --- execution role ----------------------------------------------------------

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-task-execution"
  description        = "Used by the ECS agent to pull images, read secrets and write logs."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

# The AWS managed policy covers ECR pulls and CloudWatch log writes.
resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  # Named secrets only. A wildcard on the name prefix would let any task read
  # every secret under it, including ones added later for another purpose.
  statement {
    sid       = "ReadPlatformSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }

  # A secret is encrypted with KMS, so reading one needs kms:Decrypt as well as
  # the secretsmanager permission above.
  dynamic "statement" {
    for_each = var.secrets_kms_key_arn == null ? [] : [var.secrets_kms_key_arn]
    content {
      sid       = "DecryptWithCustomerKey"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [statement.value]
    }
  }

  # With the AWS managed key there is no key ARN to name, so the permission is
  # instead confined to decryption performed by Secrets Manager on this
  # account's behalf. Without the condition this would be a general decrypt
  # permission on every key in the account.
  dynamic "statement" {
    for_each = var.secrets_kms_key_arn == null ? [1] : []
    content {
      sid       = "DecryptWithManagedSecretsKey"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = ["*"]

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["secretsmanager.${data.aws_region.current.region}.amazonaws.com"]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:CallerAccount"
        values   = [data.aws_caller_identity.current.account_id]
      }
    }
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${var.name_prefix}-read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# --- task role ---------------------------------------------------------------

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  description        = "Assumed by the application code inside the container."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task" {
  # X-Ray accepts segments only through these two calls, and neither takes a
  # resource, so a wildcard is the only expressible form.
  statement {
    sid    = "WriteTraces"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  # ECS Exec, for `aws ecs execute-command` into a running task. Enabled only
  # where the environment asks for it.
  dynamic "statement" {
    for_each = var.enable_execute_command ? [1] : []
    content {
      sid    = "EcsExec"
      effect = "Allow"
      actions = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
      ]
      resources = ["*"]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name_prefix}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

locals {
  # Both are required. A provider ARN with no subject patterns would build a
  # StringLike condition with an empty value list, which AWS rejects as an
  # invalid trust policy — a failure that lands in the middle of an apply.
  create_github_role = var.github_oidc_provider_arn != null && length(var.github_subject_patterns) > 0
}

# --- CI/CD deployment role ---------------------------------------------------
# GitHub Actions assumes this role through OIDC. No long-lived access key is
# stored in the repository.

data "aws_iam_policy_document" "github_assume" {
  count = local.create_github_role ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # The role is bound to one repository, and to the branches and environments
    # listed. A workflow in a fork cannot assume it.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = var.github_subject_patterns
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count = local.create_github_role ? 1 : 0

  name               = "${var.name_prefix}-github-deploy"
  description        = "Assumed by GitHub Actions through OIDC to push images and update services."
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
  tags               = var.tags
}

data "aws_iam_policy_document" "github_deploy" {
  count = local.create_github_role ? 1 : 0

  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PushImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
    ]
    resources = var.ecr_repository_arns
  }

  statement {
    sid    = "DeployServices"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
      "ecs:RunTask",
    ]
    resources = ["*"]
  }

  # Terraform resolves each secret ARN with DescribeSecret, and reads the
  # database password ephemerally to hand to `password_wo`. The delivery
  # workflow additionally reads the client secrets to run the smoke test against
  # the deployed environment. Read only, and only this environment's secrets.
  statement {
    sid       = "ReadPlatformSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }

  # Terraform reads the configuration subtree by path, so this one is a prefix
  # rather than a list of names. Nothing under it is a secret.
  statement {
    sid       = "ReadPlatformConfiguration"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = var.config_parameter_arns
  }

  statement {
    sid       = "PassTaskRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.task.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  count = local.create_github_role ? 1 : 0

  name   = "${var.name_prefix}-github-deploy"
  role   = aws_iam_role.github_deploy[0].id
  policy = data.aws_iam_policy_document.github_deploy[0].json
}
