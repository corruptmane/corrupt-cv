#!/bin/sh
# LocalStack init hook: runs once S3 is ready. Creates the PDF bucket.
set -e
awslocal s3 mb "s3://${S3_BUCKET:-cv-pdfs}" || true
echo "localstack: bucket ${S3_BUCKET:-cv-pdfs} ready"
