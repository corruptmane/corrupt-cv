# ADR 0008: Postgres + external goose migrations; S3 storage via OpenDAL/aws-sdk-go-v2; Swift s3api as dev backend

## Status

Accepted

## Context

Job history needs a relational store; rendered PDFs need object storage reachable from both a Python writer (cv-generator) and a Go reader (gateway). The dev stack is compose-only, so the S3 backend must run as a container.

## Decision

- **Postgres 17** with **goose** migrations as plain SQL in `migrations/`, run by an external one-shot compose job (`deploy/compose/Dockerfile.migrate`) before the gateway starts — services never migrate their own schema at boot.
- **S3 API as the storage contract**: cv-generator writes via **OpenDAL** (Python), the gateway reads via **aws-sdk-go-v2 s3-only** (the Go OpenDAL binding ships no darwin native lib, which broke local development).
- Dev backend: **OpenStack Swift all-in-one (`openstackswift/saio`) with the s3api middleware**, tempauth creds `test:tester`/`testing`, path-style addressing. MinIO was rejected by preference. Note: the s3api enforces S3 bucket-name rules, so the bucket is `cvs` (names must be ≥3 chars — `cv` is invalid on AWS too).
- **Downloads are proxied through the gateway** (`/jobs/{id}/download` streams from S3). Presigned URLs were rejected: they would embed the compose-internal endpoint host (`http://swift:8080`), unreachable from the browser, and they bypass the gateway's session check that scopes downloads to the visitor who owns the job.

## Consequences

- Plain-SQL migrations are reviewable, and the one-shot job makes ordering explicit (`depends_on: migrate: service_completed_successfully`).
- The S3-contract boundary means swapping Swift for any S3-compatible store (or real AWS) is pure configuration.
- Proxied downloads put PDF bytes through the gateway — fine at this scale, revisit with presigning + public endpoints when a real edge exists.
- The saio image is amd64-only; Apple Silicon runs it under emulation (`platform: linux/amd64`), which is acceptable for a dev dependency.

## Alternatives considered

- **Migrations at service boot (embedded goose/tern)** — rejected: racy with multiple replicas and hides schema changes in service logs.
- **MinIO** — functional, rejected by stack preference for Swift.
- **Presigned URLs** — rejected as above (internal-host problem + visitor scoping).
- **OpenDAL in Go too** — rejected: darwin gap in the Go binding.
