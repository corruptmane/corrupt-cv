variable "aws_region" {
  description = "Region for the bucket and SSM parameters."
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "AWS CLI profile used for resource management."
  type        = string
  default     = "personal-admin"
}

variable "ssm_prefix" {
  description = "Prefix for SSM parameters, matching the homelab's flat /homelab/<kebab> convention consumed by External Secrets Operator."
  type        = string
  default     = "/homelab"
}
