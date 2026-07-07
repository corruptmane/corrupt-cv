# ADR 0007: Model catalog as YAML-seeded NATS KV dynconfig

## Status

Accepted

## Context

The UI offers a fixed set of LLM choices; ai-processor must map a user's choice to a provider + model id. Accepting raw model ids from user input would let users drive arbitrary provider calls, and hardcoding the list in two services would drift.

## Decision

A **NATS KV bucket (`model-catalog`)** holds the catalog, keyed by catalog key (e.g. `anthropic/claude-sonnet-4-5`). The gateway seeds it at boot from `configs/model-catalog.yaml` (bind-mounted in compose, so edits need only a gateway restart, not an image rebuild). Selection is **key-based only**: the UI renders keys from the bucket, and ai-processor resolves the submitted key against the bucket, rejecting anything unknown. The `fake/canned-cv` entry short-circuits provider calls entirely and needs no API key.

## Consequences

- One authoritative list consumed by both languages over infrastructure that already exists in the stack — no config service, no duplicate constants.
- Users can never smuggle arbitrary model ids or providers; adding a model is a YAML edit + restart.
- KV reuses the JetStream single-authority pattern (ADR 0004): gateway creates and seeds, ai-processor only reads.

## Alternatives considered

- **Hardcoded lists in each service** — rejected: guaranteed drift between UI and worker.
- **Catalog table in Postgres** — rejected: ai-processor would gain a Postgres dependency it otherwise doesn't have.
- **Free-form model id passthrough** — rejected: input-validation and abuse surface.
