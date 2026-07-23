# App configuration handed to the cluster via the existing
# tofu -> SSM -> External Secrets Operator -> Secret chain. Parameter names
# follow the homelab's flat /homelab/<kebab> convention; the ExternalSecret
# in deploy/k8s/apps references them by these exact names.

resource "aws_ssm_parameter" "s3_endpoint" {
  name  = "${var.ssm_prefix}/cvgen-s3-endpoint"
  type  = "String"
  value = "https://s3.${var.aws_region}.amazonaws.com"
}

resource "aws_ssm_parameter" "s3_region" {
  name  = "${var.ssm_prefix}/cvgen-s3-region"
  type  = "String"
  value = var.aws_region
}

resource "aws_ssm_parameter" "s3_bucket" {
  name  = "${var.ssm_prefix}/cvgen-s3-bucket"
  type  = "String"
  value = aws_s3_bucket.cvs.bucket
}

resource "aws_ssm_parameter" "s3_access_key_id" {
  name  = "${var.ssm_prefix}/cvgen-s3-access-key-id"
  type  = "SecureString"
  value = aws_iam_access_key.cvgen_app.id
}

resource "aws_ssm_parameter" "s3_secret_access_key" {
  name  = "${var.ssm_prefix}/cvgen-s3-secret-access-key"
  type  = "SecureString"
  value = aws_iam_access_key.cvgen_app.secret
}

# HMAC key for the gateway's signed visitor cookies; consumed as raw bytes,
# so any high-entropy string works.
resource "random_password" "session_secret" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "session_secret" {
  name  = "${var.ssm_prefix}/cvgen-session-secret"
  type  = "SecureString"
  value = random_password.session_secret.result
}
