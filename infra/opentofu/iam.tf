# Single least-privilege app user shared by the gateway (GetObject) and
# cv-generator (PutObject). No ListBucket: the gateway maps NoSuchKey to a
# 404 on its own.
resource "aws_iam_user" "cvgen_app" {
  name = "cvgen-app"
}

data "aws_iam_policy_document" "cvgen_app" {
  statement {
    sid       = "CvgenObjectReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.cvs.arn}/cvs/*"]
  }
}

resource "aws_iam_user_policy" "cvgen_app" {
  name   = "cvgen-app-s3"
  user   = aws_iam_user.cvgen_app.name
  policy = data.aws_iam_policy_document.cvgen_app.json
}

resource "aws_iam_access_key" "cvgen_app" {
  user = aws_iam_user.cvgen_app.name
}
