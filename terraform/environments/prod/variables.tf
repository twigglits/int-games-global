# The domain, the ACM certificate, the hosted zone, the GitHub OIDC provider,
# the alarm topic and the access log bucket are all read from Parameter Store
# at plan time, so none of them is a variable any more. Write them once with:
#   ./scripts/bootstrap_parameters.sh prod

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "image_tag" {
  description = "Image tag to deploy. Always an explicit commit SHA in production."
  type        = string

  validation {
    condition     = var.image_tag != "latest"
    error_message = "image_tag must be an explicit tag. 'latest' in production means nobody can say which code is running."
  }
}

variable "owner" {
  description = "Team that owns this environment."
  type        = string
  default     = "platform-team"
}

variable "cost_centre" {
  description = "Cost centre this environment bills to."
  type        = string
  default     = "engineering"
}

variable "github_subject_patterns" {
  description = "Allowed values of the GitHub OIDC `sub` claim. GitHub issues ID-qualified subjects (owner@id/repo@id); the plain form is kept for the case where that setting is turned off."
  type        = list(string)
  default = [
    "repo:twigglits/int-games-global:ref:refs/heads/main",
    "repo:twigglits@51879985/int-games-global@1336288914:ref:refs/heads/main",
    "repo:twigglits/int-games-global:environment:production",
    "repo:twigglits@51879985/int-games-global@1336288914:environment:production",
    "repo:twigglits/int-games-global:environment:prod-teardown",
    "repo:twigglits@51879985/int-games-global@1336288914:environment:prod-teardown",
  ]
}

variable "force_destroy" {
  description = "Disarm the guards that stop `terraform destroy` from completing. Set only by the teardown workflow. See the root module's variable of the same name."
  type        = bool
  default     = false
}
