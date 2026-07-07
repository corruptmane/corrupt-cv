# 0001. Monorepo with path-filtered per-service CI

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

This project is a per-job-tailored CV generator and, more importantly, a
platform-engineering showcase: a single solo maintainer, a vertical slice across
multiple languages/runtimes (Go/Gin `gateway`, Python `ai-processor`,
Python `cv-generator`), a shared internal library (`libs/cvworker`), generated
protobuf stubs in two languages (`proto/gen/go`, `proto/gen/python`), and async choreography
where every service talks over NATS subjects `cv.{jobID}.{type}` with protobuf
`cv.v1` payloads.

The dominant force is **coupling at the contract boundary**. A change to a
`proto/cv/v1` message ripples to: the `buf`-generated stubs in `proto/gen/`, the
`gateway` publisher/persister, the `ai-processor` consumer (`cv.*.requested`),
the `cv-generator` consumer (`cv.*.structured`), and the proto↔Pydantic mapping
in `cvworker`. We want one reviewable, atomically-mergeable change for that, not
a coordinated dance across repos. Competing forces: keep a solo maintainer's
overhead near zero, and still **demonstrate** real per-service CI/CD (the point
of the showcase), not collapse everything into one undifferentiated build.

## Decision

Use a **single monorepo** containing all services, the shared lib, the proto
sources, and the checked-in generated stubs. Wire language workspaces so the
services compose without publishing internal packages:

- **Python**: a `uv` workspace (`[tool.uv.workspace]` members `proto/gen/python`,
  `libs/cvworker`, `services/ai-processor`, `services/cv-generator`). Both
  workers depend on `cv-worker` and `cv-contracts` as local path members; CI
  runs `uv sync --all-packages`.
- **Go**: `go.work` (`use ./proto/gen/go`, `./services/gateway`) so the gateway
  consumes the generated `proto/gen/go/cv` module via a local replace, no tag/publish.

CI/CD is **per-service via GitHub Actions `paths:` filters**, so each workflow
only runs for the files it owns:

- `gateway.yml` → `services/gateway/**`, `proto/gen/go/**`, `proto/**`, `go.work`
- `ai-processor.yml` → `services/ai-processor/**`, `libs/cvworker/**`,
  `proto/gen/python/**`, `pyproject.toml`, `uv.lock`
- `cv-generator.yml` → analogous for the generator
- `proto.yml` → `proto/**`, `buf.yaml`, `buf.gen.yaml`, `proto/gen/**` (lint, format,
  breaking-change vs `main`, and `buf generate && git diff --exit-code`)
- `images.yml` → matrix build/push of all three images to GHCR on `main`

## Alternatives considered (with why-not for each)

- **Multi-repo (one repo per service + a shared `contracts` repo).** Rejected.
  A single protobuf change becomes N+1 PRs across N+1 repos, gated on publishing
  a new `cv.v1` stub version and bumping each consumer — exactly the
  cross-service atomicity we need most. The reproducible-codegen discipline
  (pinned `buf` remote plugins) is far easier to enforce when proto sources and
  the verifying `proto.yml` job live beside the stubs they generate.
- **Polyrepo with a git-submodule contracts repo.** Rejected. Submodule pointer
  bumps are a notorious solo-maintainer footgun and obscure the atomic
  proto→stub→consumer diff that a monorepo shows in one review.
- **Monorepo but one monolithic CI pipeline (no path filters).** Rejected. It
  would rebuild Go on a Typst-template edit and run the Python suite on a
  `gateway` change, wasting minutes and — for a showcase — failing to
  demonstrate independent, service-scoped delivery.

## Consequences (positive and negative/trade-offs)

Positive:
- Atomic cross-service changes: edit `proto/cv/v1`, regenerate `proto/gen/`, and
  update gateway + both workers + `cvworker` mapping in one PR; `proto.yml`
  proves the stubs are regenerated and unchanged drift-free.
- One `docker-compose.yml` and one `Justfile` (`just up`) bring up the whole
  slice; `go.work` + the `uv` workspace mean local cross-service edits are
  instant with no publish step.
- Per-service CI is still real and visible: independent `gateway`,
  `ai-processor`, `cv-generator`, and `proto` workflows, scoped by `paths:`.

Negative / trade-offs:
- `paths:` filters are a coarse approximation of a true build graph; they must
  be kept in sync by hand (e.g. `libs/cvworker/**` is listed under both Python
  services because a shared-lib edit must trigger both). A missed entry silently
  skips a job.
- The generated `proto/gen/` tree is checked in and must stay current, enforced by the
  `git diff --exit-code` gates rather than produced fresh per build.
- Single-repo permissions are all-or-nothing — acceptable for a solo portfolio
  repo, less so for multi-team ownership.

## Sets up

The monorepo + checked-in image matrix (`images.yml` → GHCR) is the substrate
for the deferred delivery layer: Kubernetes manifests, Flux GitOps, and
progressive delivery (Argo Rollouts/Flagger-style canary) all expect a single
source repo and ready GHCR tags per service, which this layout already produces.
