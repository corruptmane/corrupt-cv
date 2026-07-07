# 0004. Versioned protobuf contracts via buf

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

Three services in two languages must agree on the wire format without sharing
runtime code: the Go/Gin `gateway`, the Python `ai-processor`, and the Python
`cv-generator`. They communicate only over NATS JetStream (stream `CV`, subjects
`cv.{jobID}.{type}`), and the payloads are binary, not JSON — see
`docs/CONVENTIONS.md`. Each subject type maps to a specific message
(`requested → GenerationRequest`, `structured → CVStructured`,
`completed → CVCompleted`, `failed → CVFailed`), and the `CV` message is 1:1 with
the canonical Pydantic CV model used by PydanticAI as its `output_type`.

Forces:
- One contract, two languages — Go structs and Python classes must be generated
  from a single source, not hand-synced.
- Binary efficiency and forward/backward-compatible field evolution on a
  persisted bus (JetStream keeps messages).
- The contract must be lint-clean, breaking-change-checked, and the generated
  stubs must never drift from the `.proto` source.
- Reproducible codegen: the same `.proto` must produce byte-identical stubs on
  any machine and in CI, independent of locally installed compiler versions.

## Decision

Define the contract as protobuf under package `cv.v1` in `proto/cv/v1/*.proto`
(`cv.proto`, `generation.proto`), managed by **buf** (`buf.yaml` v2: module
`proto`, `STANDARD` lint, `FILE` breaking rules).

Generate stubs for both languages with **pinned remote plugins** (`buf.gen.yaml`)
and check the output into `proto/gen/`:
- Go: `buf.build/protocolbuffers/go:v1.36.6` → `proto/gen/go/cv/v1/*.pb.go`
  (`paths=source_relative`), consumed via `go.work` + `replace`.
- Python: `buf.build/protocolbuffers/python:v31.1` plus the matching `pyi`
  plugin → `proto/gen/python/cv/v1/*_pb2.py(.pyi)`, packaged as the `cv-contracts`
  wheel that both Python services depend on (alongside `libs/cvworker`).

CI (`.github/workflows/proto.yml`, path-filtered on `proto/**`, `buf.yaml`,
`buf.gen.yaml`, `proto/gen/**`) runs `buf lint`, `buf format --diff --exit-code`,
`buf-breaking-action` against `main`, then regenerates and asserts
`git diff --exit-code -- gen` so checked-in stubs can never be stale.

## Alternatives considered (with why-not for each)

- **JSON Schema + hand-rolled (de)serialization.** Text-on-the-wire is heavier
  on a persisted bus, has no native cross-language codegen story, and gives no
  built-in breaking-change tooling. The Pydantic models already validate the AI
  output; JSON Schema would duplicate that without solving the Go side.
- **OpenAPI.** It models request/response HTTP APIs, not fire-and-forget event
  payloads on NATS subjects. We have no REST contract between services to
  describe — the integration is choreography, not RPC.
- **Hand-written DTOs per language.** Two sources of truth that must be kept in
  lockstep by humans; the exact failure mode (Go/Python skew) we are designing
  out. No lint, no breaking detection, no generated `.pyi` types.

## Consequences (positive and negative/trade-offs)

Positive:
- Single source of truth; `gateway`, `ai-processor`, and `cv-generator` cannot
  disagree on the wire format. `buf breaking` blocks accidental contract breaks.
- Compact binary payloads, well-suited to JetStream retention.
- Checked-in stubs mean consumers build without running buf; CI's
  regenerate-and-diff guarantees they match the source.

Negative / trade-offs:
- `proto/gen/` is generated code under version control; `buf.gen.yaml` sets
  `clean: false` because `proto/gen/python` carries a hand-written `pyproject.toml` and
  `__init__.py` next to the generated `*_pb2.py`, so the diff-guard (not `clean`)
  enforces freshness.
- proto3 enums force the `LANGUAGE_PROFICIENCY_*` / `PROVIDER_*` name-prefix and a
  zero `*_UNSPECIFIED` value; string forms (`NATIVE`, `FLUENT`, ...) are mapped
  in code, an extra hop the `strict=True` Pydantic models must absorb.

**Pinned-plugins lesson (gencode/runtime skew):** plugin versions are pinned
*because* unpinned remote plugins emit gencode newer than any released runtime —
generated `*_pb2.py` would import a protobuf API that the installed
`protobuf` wheel doesn't ship, breaking imports at runtime. The pins are chosen
to track released runtimes: `protocolbuffers/go v1.36.6` ↔
`google.golang.org/protobuf v1.36.6`, and `protocolbuffers/python v31.1` ↔
`protobuf>=6.31,<7` (the `cv-contracts` dependency). Pinning also makes codegen
reproducible across machines and CI.

## Sets up

A stable, versioned `cv.v1` package leaves room for a future `cv.v2` evolved
under buf's breaking-change discipline, and gives any later out-of-process or
cross-language consumer (e.g. a Kubernetes-deployed worker) a published,
generated contract rather than tribal knowledge of the JSON shape.
