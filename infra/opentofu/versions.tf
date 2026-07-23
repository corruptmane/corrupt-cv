terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.36"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8"
    }
  }

  # Partial backend configuration: the state bucket, lock table, region and
  # profile are supplied via a gitignored backend.hcl (see
  # backend.example.hcl) so private infrastructure identifiers stay out of
  # this public repo.
  #   tofu init -backend-config=backend.hcl
  backend "s3" {
    key = "aws/cvgen/terraform.tfstate"
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}
