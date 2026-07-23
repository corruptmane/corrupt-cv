# ADR 0013: OpenTofu-managed AWS S3 with secret handoff via SSM + External Secrets Operator

## Status

Accepted

## Context

The homelab hosts everything except durable object storage; rendered PDFs
need an external S3. The cluster already syncs secrets from AWS SSM
Parameter Store through External Secrets Operator, and the user's private
infra repo established OpenTofu conventions (shared S3 state bucket,
DynamoDB locking, profile separation).

## Decision

- `infra/opentofu/` provisions the only external infrastructure: an S3
  bucket (`cvgen-cvs-<random>`, public access blocked, SSE-S3, 30-day
  lifecycle on `cvs/`, versioning off — PDFs are regenerable), a
  least-privilege IAM user (`s3:GetObject` + `s3:PutObject` on
  `arn:.../cvs/*` only), and six SSM parameters under the homelab's flat
  `/homelab/cvgen-*` naming.
- **Secret handoff chain: tofu → SSM → ESO → Secret → envFrom.** The
  ExternalSecret's keys are named exactly like the env vars
  (`S3_ACCESS_KEY_ID`, …, `SESSION_SECRET`), so Deployments consume the
  synced Secret verbatim. Rotation = `tofu apply` + ESO refresh (1h, or
  forced) + rollout restart.
- **Partial backend configuration**: only the state `key` is committed;
  bucket/region/lock-table/profile live in a gitignored `backend.hcl`
  (example committed), keeping private state-infrastructure identifiers
  out of this public repo while reusing the existing state bucket.

## Consequences

- No secret value ever exists in either git repo, in NATS, or in Postgres;
  the session HMAC secret is generated inside tofu (`random_password`) and
  never seen by a human.
- The dev/prod split is pure configuration: compose points the same env
  contract at Swift s3api with path-style; production points at AWS with
  virtual-host style (`S3_USE_PATH_STYLE=false`).

## Alternatives considered

- **Cloudflare R2 / Hetzner / B2** — viable and cheaper at scale, but AWS
  was chosen for ecosystem familiarity and because SSM+ESO already anchor
  the homelab's secret flow.
- **Committing full backend config** — rejected: state-bucket identifiers
  are private-repo material.
- **IRSA/role-based auth** — not applicable from a homelab; static keys
  scoped to one prefix are the pragmatic floor.
