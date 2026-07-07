# 0010. Object storage: OpenDAL in Python, aws-sdk-go-v2 in Go

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The pipeline produces one artifact that outlives a bus message: the rendered
PDF. Two services touch it from opposite ends of the choreography. The
`cv-generator` (Python) writes the PDF to object storage at key
`pdfs/{jobID}.pdf` after consuming `cv.*.structured`, then emits
`cv.*.completed` carrying only the object key (never the bytes). The `gateway`
(Go/Gin) reads that same key back to stream the PDF to the browser on download.
Postgres stores only the key (`pdf_object_key`); the bytes live in S3.

The forces:

- **One storage contract, two languages.** Both services share the same
  `S3_*` env vars (`S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`,
  `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_USE_PATH_STYLE`) per
  `docs/CONVENTIONS.md`, so whatever clients we pick must agree on the same
  bucket/key/path-style semantics.
- **Local now, AWS later.** v1 runs against LocalStack (`localstack:4566`,
  `SERVICES: s3`), which requires **path-style** addressing and a
  `BaseEndpoint` override. The exact same client must work against real AWS S3
  once the bucket is OpenTofu-provisioned, with only env-var changes.
- **macOS dev parity.** The whole stack must build on darwin (developer laptops)
  and Linux (CI/containers) from one codebase.
- **No bloat.** This is a showcase; dependencies should be minimal and
  intentional, not kitchen-sink SDKs.

## Decision

**S3 API everywhere; one storage client per language, chosen for that
language's ecosystem:**

- **Python `cv-generator` → OpenDAL.** `cv_generator/storage.py` constructs an
  `opendal.AsyncOperator("s3", ...)` with `endpoint`, `region`, `bucket`, and
  static `access_key_id` / `secret_access_key`, plus
  `disable_config_load="true"` and `disable_ec2_metadata="true"` so it uses only
  the supplied creds and never probes AWS config or EC2 IMDS. OpenDAL defaults to
  path-style addressing, which LocalStack needs. The write path is a single
  `await self._op.write(key, data)`. Dependency: `opendal>=0.45` (mature,
  cross-platform wheels).
- **Go `gateway` → aws-sdk-go-v2, `service/s3` only.**
  `internal/storage/storage.go` builds `s3.New(s3.Options{...})` with
  `BaseEndpoint: aws.String(cfg.Endpoint)`, `UsePathStyle: cfg.UsePathStyle`,
  and `credentials.NewStaticCredentialsProvider(...)`. Reads use `GetObject`,
  returning the body and size for streaming. Dependencies are the modular
  `aws-sdk-go-v2`, `.../credentials`, and `.../service/s3` only — not the full
  AWS SDK.

Both point at the same bucket and the same `pdfs/{jobID}.pdf` key; the
`BaseEndpoint` + path-style combination is the single switch that retargets
LocalStack now and AWS S3 later.

## Alternatives considered (with why-not for each)

- **OpenDAL everywhere (Go gateway on OpenDAL too).** Rejected — **BLOCKED on
  macOS.** The OpenDAL Go binding's scheme modules embed Linux-only native libs;
  there is no darwin build, so the gateway would fail to compile on developer
  laptops. Using OpenDAL in Python (where the wheels are mature and
  cross-platform) but aws-sdk-go-v2 in Go is the only combination that builds on
  both darwin and Linux from one repo.
- **boto3 in the Python `cv-generator`.** Rejected as bloat. OpenDAL gives the
  thin write surface we need (one `write` call) without pulling botocore's
  weight, and keeps a single storage abstraction that could later swap backends
  (fs, gcs, azblob) behind the same `Storage` class.
- **Full AWS SDK for Go (not just `service/s3`).** Rejected — unnecessary
  surface. aws-sdk-go-v2 is modular; depending on `service/s3` (+ `credentials`)
  only keeps the gateway's dependency graph small and the binary lean.

## Consequences (positive and negative/trade-offs)

Positive:

- **Builds on darwin and Linux** from one monorepo — the macOS blocker that
  killed OpenDAL-in-Go is sidestepped while Python still gets OpenDAL's nice API.
- **Single S3 contract.** Both services share the `S3_*` env vars and the
  `pdfs/{jobID}.pdf` key convention; the backend swap (LocalStack → AWS S3) is
  pure configuration via `BaseEndpoint`/`S3_ENDPOINT` and `S3_USE_PATH_STYLE`.
- **Minimal dependencies.** `opendal` on one side, `service/s3`-only on the
  other; no boto3, no monolithic AWS SDK.
- **Credential hygiene.** Both clients use the supplied static creds explicitly
  and the Python side disables config/IMDS probing, so behaviour is identical and
  predictable across local and CI.

Negative / trade-offs:

- **Two different client libraries** to understand and keep working — the storage
  layer is not symmetric across services; a future bug or option (e.g. checksum,
  retry) must be reasoned about twice.
- **Path-style is hard-wired for local.** It is correct for LocalStack but
  virtual-hosted-style is the AWS default; the `S3_USE_PATH_STYLE` flag must be
  flipped (and verified) when moving to real S3.
- **OpenDAL's S3 layer abstracts away** some AWS-specific knobs; if we later need
  fine-grained S3 features on the write path we may bump into the abstraction.

## Sets up

- The clean `S3_*` contract and `BaseEndpoint`/path-style switch are exactly the
  seam the deferred **OpenTofu-provisioned AWS S3 bucket** plugs into — flip the
  endpoint/region/credentials, drop path-style, no code change.
- A backend-agnostic storage layer in both services keeps the door open for the
  deferred Kubernetes/Flux move (IRSA/static-cred injection) without touching the
  application logic.
