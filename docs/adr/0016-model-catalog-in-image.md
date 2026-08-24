# 16. Model catalog baked into the gateway image

Date: 2026-08-24

## Status

Accepted

## Context

Catalog entries are executable contracts, not display data. Each entry
pairs a closed protobuf `Provider` enum value (defined in
`proto/cvgen/catalog/v1/catalog.proto`) with a `model_id` string that
only the ai-processor code of the matching version knows how to drive.
The gateway loads `configs/model-catalog.yaml` at boot and upserts every
entry into the `model-catalog` NATS KV bucket (ADR 0007); the UI offers
only those keys, and ai-processor rejects any key absent from the bucket
— raw model ids are never accepted from user input.

Today the file reaches the gateway two ways. The image copies it to
`/etc/cvgen/model-catalog.yaml` at build time, and compose bind-mounts
the repo copy over that path so local edits need only a gateway restart.
The k8s manifests set the same `MODEL_CATALOG_PATH` but ship no
bind-mount, so in production the in-image copy is authoritative.

## Decision

Keep the catalog in the image: `COPY configs/model-catalog.yaml
/etc/cvgen/model-catalog.yaml` stays in the gateway Dockerfile, now as a
deliberate choice rather than an accident. The catalog version travels
atomically with the code that understands it — an image can never serve
entries its sibling ai-processor cannot execute, because both are built
and tagged from the same commit. The compose bind-mount remains the
development fast path: edit the repo YAML, restart the gateway, no
rebuild.

A catalog change therefore rides the normal pipeline — image build, CI
tag, Flux image automation bump, Flagger canary — instead of behaving
like an instantly pushable config file.

## Consequences

- Catalog changes release at image cadence, not config cadence. Adding
  a model means going through the full promote path; in exchange, the
  provider/model_id pair and the ai-processor code that drives it always
  deploy together.
- Decoupling the catalog from the image via a ConfigMap rollout was
  considered and rejected: catalog and ai-processor would then reconcile
  on independent schedules, reintroducing the race where a rolled-out
  catalog references providers or models the running ai-processor cannot
  handle (or vice versa).
- Seeding is upsert-only, so entries removed from the YAML currently
  linger in the KV bucket until evicted by hand. Automatic eviction of
  retired keys is being addressed separately and is out of scope here.
