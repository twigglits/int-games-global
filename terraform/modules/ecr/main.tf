/**
 * ECR repositories, one per image the platform builds.
 *
 * Two settings are deliberate:
 *
 *   * Images are immutable. A tag that has been pushed can never point at
 *     different bytes, so "the image running in production" is a question with
 *     one answer.
 *   * Scan on push is on, so a new image is checked for known vulnerabilities
 *     before anybody schedules it.
 */

locals {
  repositories = toset(var.repository_names)
}

resource "aws_ecr_repository" "this" {
  for_each = local.repositories

  name                 = "${var.name_prefix}/${each.value}"
  image_tag_mutability = var.image_tag_mutability
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = var.kms_key_arn == null ? "AES256" : "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-${each.value}" })
}

# Untagged layers accumulate on every push. The policy keeps the repository from
# growing without bound while never touching a tagged release.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_expiry_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the ${var.retained_image_count} most recent tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-", "main-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.retained_image_count
        }
        action = { type = "expire" }
      },
    ]
  })
}
