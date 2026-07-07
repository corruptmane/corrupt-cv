# ADR 0001: Monorepo layout and tooling

## Status

Accepted

## Context

The project spans a Go gateway, two Python workers, shared protobuf contracts, SQL migrations, and compose deployment. Splitting these across repositories would add contract-versioning ceremony for a system built and reviewed as one unit.

## Decision

A single monorepo:

- `proto/` — protobuf sources; `libs/python/cv-shared/` and `services/gateway/gen/` hold committed generated code.
- `services/gateway/` — a single self-contained Go module (`go.mod` lives there, not at the root).
- `services/ai-processor/`, `services/cv-generator/`, `libs/python/cv-shared/` — members of one uv workspace rooted at the top-level `pyproject.toml` with a single shared `uv.lock`.
- `just` as the task runner (`just up`, `just lint`, `just e2e`); it wraps buf, uv, go, and docker compose so nobody memorizes flags.
- Generated code is committed rather than produced at build time; CI regenerates and fails on drift (see ADR 0003).

## Consequences

- One clone, one lockfile, one `just up` gives the entire system.
- Committed codegen keeps `go build` and `uv sync` hermetic — no buf needed to build.
- The Go module living under `services/gateway/` keeps Go tooling happy without polluting the root; the cost is `cd services/gateway` (wrapped by just targets).

## Alternatives considered

- **Polyrepo** — rejected: contract drift and release coordination overhead for a single-team portfolio project.
- **Root-level Go module** — rejected: mixes Go module boundaries with non-Go trees and complicates Docker build contexts.
- **Codegen at build time** — rejected: every builder (CI, Docker, contributors) would need buf + plugins installed.
