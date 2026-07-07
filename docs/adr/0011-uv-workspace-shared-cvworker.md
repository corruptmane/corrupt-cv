# 0011. uv workspace with a shared cv-worker library

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The repo holds two Python services — `ai-processor` (consumes `cv.*.requested`,
emits `cv.*.structured`) and `cv-generator` (consumes `cv.*.structured`, emits
`cv.*.completed`) — plus the generated protobuf package in `proto/gen/python`
(`cv-contracts`). Both services are *stateless reactors on the same bus*: they
share an identical runtime spine.

Forces:
- Both need the same plumbing: `pydantic-settings`-backed config over the
  canonical env vars (`NATS_URL`, `NATS_STREAM`, `OTEL_EXPORTER_OTLP_*`,
  `HEALTH_ADDR`, `LOG_LEVEL`, …), structured **structlog** JSON logging with the
  required fields (`time`/`level`/`msg`/`service`, plus `job_id`/`trace_id`/`span_id`),
  OTel setup (traces push, metrics via a Prometheus reader), NATS JetStream connect
  + publish/consume helpers that inject and extract the W3C `traceparent` header,
  and an ops server (`/livez`, `/readyz`, `/metrics`).
- They share *semantics*, not just code: the canonical strict Pydantic CV models
  and the proto↔Pydantic mapping must be byte-for-byte identical on both ends,
  because `ai-processor` produces the `CVStructured` body that `cv-generator`
  binds natively into Typst. A drift between two copies would be a silent
  contract break that no protobuf check would catch.
- Single repo (ADR 0001), single Python pin (`>=3.13,<3.14`), one lockfile, one
  set of dev tools (`ruff`, `ty`, `pytest`). We want one resolution, not three.
- Per-service Docker images must stay thin: each container should install only
  its own service plus the shared lib and contracts — not the other service's
  deps (PydanticAI/`redis` vs `typst`/`opendal`).

## Decision

Use a single **uv workspace** rooted at the repo's `pyproject.toml`
(`[tool.uv.workspace] members = ["proto/gen/python", "libs/cvworker",
"services/ai-processor", "services/cv-generator"]`, `package = false` at root).
One `uv.lock` resolves the whole graph; dev tooling lives in the root
`[dependency-groups] dev`.

Extract the shared runtime into one internal library, **`libs/cvworker`**
(distribution `cv-worker`, import package `cv_worker`), owning: settings,
structlog logging, OTel setup, NATS bus helpers, the ops server, the canonical
Pydantic CV models, and the proto↔Pydantic mapping. Both services depend on
`cv-worker` and `cv-contracts`, wired as workspace sources:

```toml
[tool.uv.sources]
cv-worker = { workspace = true }
cv-contracts = { workspace = true }
```

So `cv-worker` itself depends on `cv-contracts` (the generated stubs), keeping
the models + mapping next to the proto types they translate.

Per-service Docker builds install exactly one service via `uv sync --package`:

```dockerfile
COPY pyproject.toml uv.lock ./
COPY proto/gen/python ./proto/gen/python
COPY libs/cvworker ./libs/cvworker
COPY services/<other>/pyproject.toml ./services/<other>/pyproject.toml
COPY services/<this> ./services/<this>
RUN uv sync --frozen --package <this> --no-dev
```

`--frozen` enforces the committed `uv.lock` (reproducible builds); `--package`
selects one workspace member so only that service's dependency closure is
installed; `--no-dev` drops `ruff`/`ty`/`pytest`. The sibling service's
`pyproject.toml` is copied (not its source) only so uv can resolve the workspace
graph against the lockfile.

## Alternatives considered (with why-not for each)

- **Duplicate the infra in each service (copy settings/logging/OTel/bus/models
  into both).** Rejected: the CV models + proto mapping are a shared *contract*
  surface; two copies drift, and a divergence between `ai-processor`'s
  `CVStructured` and `cv-generator`'s decode is exactly the silent bug we can't
  afford. Also doubles the maintenance of every cross-cutting concern.
- **No shared lib; a `cvworker` package published to an index.** Rejected as
  overweight for a docker-compose vertical slice: it adds a publish/version/pin
  loop and breaks the single-`uv.lock`, edit-and-rerun ergonomics. Workspace
  member with `workspace = true` gives the same import boundary with none of the
  release overhead.
- **Three independent venvs / separate `requirements.txt` per service.**
  Rejected: no single resolution → version skew across services and the shared
  lib, three lockfiles to keep coherent, and dev tooling pinned in three places.
- **One fat service installing both services' deps in every image.** Rejected:
  `ai-processor` would carry `typst`/`opendal` and `cv-generator` would carry
  PydanticAI/`redis` for no reason. `uv sync --package` keeps each image to its
  own closure.

## Consequences (positive and negative/trade-offs)

Positive:
- DRY + coherence: settings/logging/OTel/bus/health and, crucially, the
  canonical strict CV models + proto mapping live once in `cv_worker`, so both
  services agree by construction.
- Thin services: each `pyproject.toml` lists only its real deps
  (`ai-processor`: `pydantic-ai-slim`, `redis`; `cv-generator`: `typst`,
  `opendal`) on top of `cv-worker` + `cv-contracts`.
- One `uv.lock` for the whole graph; CI and local dev resolve identically, and
  `--frozen` images are reproducible.
- Edit-and-run: changing `cv_worker` is picked up by both services without a
  publish step (editable workspace install).

Negative / trade-offs:
- Coupling risk: `cv-worker` can become a junk drawer. Keep it to genuinely
  shared runtime + contract surface; service-specific logic stays in the service
  (e.g. the agent in `ai_processor/`, the renderer in `cv_generator/`).
- A change to `cv-worker` (e.g. a CV-model field) forces rebuilding *both*
  images, since both depend on it.
- Each Dockerfile must `COPY` the sibling's `pyproject.toml` so uv can resolve
  the workspace against `uv.lock` — a small, easy-to-forget build wart.
- Workspace-wide resolution means one service's dependency bump can shift the
  shared lockfile; reviewers must read `uv.lock` diffs with that in mind.

## Sets up

- A natural home for the next worker (or a split of `cv-generator`'s upload
  path): add a workspace member, depend on `cv-worker`, build with
  `uv sync --package`.
- The Go side has the parallel ergonomic (`go.work` + `replace`, ADR 0001); this
  ADR is the Python half of the monorepo's "shared types, thin services" story.
- Roadmap (not built here): when services move to Kubernetes, the same
  per-service `--package` images ship unchanged; only their orchestration moves.
