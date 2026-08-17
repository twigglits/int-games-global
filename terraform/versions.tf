terraform {
  # 1.11 introduced write-only arguments, which is what keeps the database
  # password out of the state file. 1.10 introduced the ephemeral resources that
  # feed them. Neither is optional here.
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
