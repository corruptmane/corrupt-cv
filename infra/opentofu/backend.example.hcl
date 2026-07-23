# Copy to backend.hcl (gitignored) and fill in the private values, then:
#   tofu init -backend-config=backend.hcl
bucket         = "your-tofu-state-bucket"
region         = "eu-central-1"
dynamodb_table = "your-tofu-state-lock-table"
profile        = "your-tofu-state-profile"
encrypt        = true
