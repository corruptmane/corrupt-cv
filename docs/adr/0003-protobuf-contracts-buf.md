# ADR 0003: Protobuf contracts via buf v2 under a cvgen namespace, committed codegen

## Status

Accepted

## Context

Gateway (Go) and workers (Python) exchange messages over NATS and share catalog/CV schemas. The contract needed one source of truth, generated code for both languages, and protection against silent breaking changes.

Python's protobuf codegen imposes a structural constraint: generated modules import each other by the proto package path, so the proto file tree must match the desired Python import path. To get `from cvgen.events.v1 import events_pb2`, sources had to live at `proto/cvgen/<pkg>/v1/*.proto`.

## Decision

- **buf v2** (`buf.yaml`, `buf.gen.yaml`) for lint, generate, and breaking-change checks.
- All packages live under the `cvgen.*` namespace: `cvgen.cv.v1`, `cvgen.events.v1`, `cvgen.catalog.v1`, laid out as `proto/cvgen/...` to satisfy the Python import-path constraint above.
- Generated code is **committed**: Go to `services/gateway/gen/`, Python to `libs/python/cv-shared/src/cvgen/`. CI runs `buf generate && git diff --exit-code` to fail on drift, and `buf breaking --against main` on PRs.

## Consequences

- Builds need no proto toolchain; contract changes are visible in review as generated-code diffs.
- Drift is impossible to merge (CI check), and breaking changes need a deliberate override.
- The `proto/cvgen/...` double-nesting looks redundant from the Go side but is the only layout that keeps Python imports clean without sys.path hacks.

## Alternatives considered

- **Generate at build time** — rejected (see ADR 0001): toolchain burden on every builder.
- **Buf Schema Registry remote packages** — rejected: external dependency and account for a self-contained portfolio repo.
- **Flat `proto/` layout with per-language rewrite tricks** — rejected: fragile Python imports.
