/**
 * Application Load Balancer.
 *
 * Only the .NET API is published. The MCP server and the embedding service are
 * reached inside the VPC through service discovery, so neither has a public
 * listener and neither can be called from outside the cluster.
 *
 * HTTPS is required. The HTTP listener exists only to redirect to it, so a
 * caller that types the URL without a scheme is corrected rather than served
 * over plaintext.
 */

resource "aws_lb" "this" {
  name               = substr("${var.name_prefix}-alb", 0, 32)
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.security_group_id]

  idle_timeout               = var.idle_timeout_seconds
  enable_deletion_protection = var.enable_deletion_protection
  enable_http2               = true
  drop_invalid_header_fields = true
  # Prevents request smuggling through a header the backend and the balancer
  # would otherwise parse differently.
  desync_mitigation_mode = "strictest"

  dynamic "access_logs" {
    for_each = var.access_logs_bucket == null ? [] : [var.access_logs_bucket]
    content {
      bucket  = access_logs.value
      prefix  = var.name_prefix
      enabled = true
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_lb_target_group" "api" {
  name        = substr("${var.name_prefix}-api", 0, 32)
  port        = var.api_container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  # The API drains in-flight requests; 30 seconds covers the 30 second request
  # timeout the service itself enforces.
  deregistration_delay = 30

  health_check {
    enabled  = true
    path     = var.health_check_path
    protocol = "HTTP"
    matcher  = "200"
    # The readiness route reaches the MCP server, so it is polled less often
    # than a liveness route would be.
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  stickiness {
    type    = "lb_cookie"
    enabled = false
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })

  lifecycle {
    create_before_destroy = true
  }
}

# --- certificate -------------------------------------------------------------
# Either an existing certificate ARN is supplied, or one is requested and
# validated through Route 53. Both paths end in a certificate; neither allows
# the listener to fall back to plaintext.

resource "aws_acm_certificate" "this" {
  count = var.certificate_arn == null ? 1 : 0

  domain_name               = var.domain_name
  subject_alternative_names = var.subject_alternative_names
  validation_method         = "DNS"

  tags = merge(var.tags, { Name = "${var.name_prefix}-certificate" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = var.certificate_arn == null && var.route53_zone_id != null ? {
    for option in aws_acm_certificate.this[0].domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  } : {}

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count = var.certificate_arn == null && var.route53_zone_id != null ? 1 : 0

  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]

  # DNS validation normally finishes in a few minutes. The provider default of
  # 75 minutes outlives the deploy role's session, so an undelegated domain
  # burns the credentials and the apply cannot write its state back.
  timeouts {
    create = "15m"
  }
}

locals {
  certificate_arn = coalesce(
    var.certificate_arn,
    try(aws_acm_certificate_validation.this[0].certificate_arn, null),
    try(aws_acm_certificate.this[0].arn, null),
  )
}

# --- listeners ---------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  # TLS 1.2 as the floor, forward secrecy required.
  ssl_policy      = var.ssl_policy
  certificate_arn = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  tags = var.tags
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = var.tags
}

# --- DNS ---------------------------------------------------------------------

resource "aws_route53_record" "alias" {
  count = var.route53_zone_id == null ? 0 : 1

  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
