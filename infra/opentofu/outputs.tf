output "bucket_name" {
  value = aws_s3_bucket.cvs.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.cvs.arn
}

output "app_user_arn" {
  value = aws_iam_user.cvgen_app.arn
}

output "ssm_parameter_names" {
  value = [
    aws_ssm_parameter.s3_endpoint.name,
    aws_ssm_parameter.s3_region.name,
    aws_ssm_parameter.s3_bucket.name,
    aws_ssm_parameter.s3_access_key_id.name,
    aws_ssm_parameter.s3_secret_access_key.name,
    aws_ssm_parameter.session_secret.name,
  ]
}
