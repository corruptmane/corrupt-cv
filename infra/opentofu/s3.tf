resource "random_id" "suffix" {
  byte_length = 4
}

# Rendered CV PDFs. Versioning stays off deliberately: objects are
# regenerable from the structured CV stored in Postgres, and job rows older
# than the retention window reference nothing anyone can still download.
resource "aws_s3_bucket" "cvs" {
  bucket = "cvgen-cvs-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "cvs" {
  bucket = aws_s3_bucket.cvs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cvs" {
  bucket = aws_s3_bucket.cvs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cvs" {
  bucket = aws_s3_bucket.cvs.id

  rule {
    id     = "expire-rendered-pdfs"
    status = "Enabled"

    filter {
      prefix = "cvs/"
    }

    expiration {
      days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
