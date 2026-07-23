# cvgen AWS infrastructure

The only external infrastructure the homelab deployment needs: the S3
bucket for rendered PDFs, a least-privilege IAM user, and the SSM
parameters that External Secrets Operator syncs into the cluster
(tofu → SSM → ESO → Secret; see ADR 0013).

```sh
cp backend.example.hcl backend.hcl   # fill in the private state-backend values
tofu init -backend-config=backend.hcl
tofu plan
tofu apply
```

Verify the handoff:

```sh
aws ssm get-parameters-by-path --path /homelab --query 'Parameters[].Name' \
  --profile personal-admin | grep cvgen
```
