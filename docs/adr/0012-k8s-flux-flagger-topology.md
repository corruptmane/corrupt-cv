# ADR 0012: Kubernetes deployment via Flux from this repo, with Flagger canaries on Cilium Gateway API

## Status

Accepted

## Context

v1 shipped on docker compose (ADR 0011) and was validated with real job
descriptions. The platform stage moves the system to the existing homelab
cluster (Talos + Cilium, Flux-managed fleet repo, CNPG operator, Victoria
observability stack, External Secrets Operator, cert-manager,
external-dns) with progressive delivery instead of manual promotion.

## Decision

- **Manifests live in this repo** (`deploy/k8s/`), split into six
  Kustomizations reconciled by the fleet repo through a `GitRepository`
  pointing here: `infra → db → migrations → apps → canary`, plus
  `image-automation`. The fleet repo owns only the pointer (see
  `docs/k8s/homelab-integration.md`); the app repo stays the single source
  of truth for how the app runs.
- **Migrations are a Flux-managed Job**: the goose image (migrations baked
  in) runs as an immutable Job whose Kustomization uses `force: true`
  (recreate on image change) and `wait: true`, so the apps layer is gated
  on schema readiness. `DATABASE_URL` comes from CNPG's generated
  `cvgen-db-app` secret (`uri` key) — no credentials authored anywhere.
- **Canary on Flagger's `gatewayapi:v1` provider**: we author the
  `cvgen-gateway` Gateway (per-app Gateway + explicit Certificate, homelab
  house style) and the gateway Deployment only; Flagger owns the Services
  and the weighted HTTPRoute. external-dns creates DNS from that HTTPRoute.
  Analysis shifts 10%-steps to 50% on two VictoriaMetrics-backed gates —
  non-5xx rate ≥99% and p99 ≤500ms from otelgin's
  `http.server.request.duration` — with a loadtester webhook generating
  synthetic traffic through the Gateway (a homelab has no organic load).
  Canary pods are discriminated from primary via `service_instance_id`
  (pod name injected as `service.instance.id`; label mapping verified
  against the live vmsingle).
- **Business metrics are not canary gates**: the events consumer is a
  shared durable, so `cvgen_jobs_*` cannot be attributed to one side.
  Running primary+canary gateways concurrently is safe by construction —
  SQL-guarded status transitions, work-shared durable consumer, idempotent
  provisioning (ADR 0005) — but provisioning-config changes should not
  rely on canary gating.
- **Rollouts via Flux image automation**: CI tags `main-<run>-<sha>`; an
  ImagePolicy extracts the run number (numerical policy) and
  ImageUpdateAutomation commits tag bumps back to this repo through the
  fleet's RW deploy key, which Flagger then canaries.

## Consequences

- One `git push` to main is the entire deployment pipeline: CI builds and
  tags, Flux bumps, Flagger canaries, metrics decide.
- The gateway Deployment authored here is scaled to zero by Flagger; the
  primary is a Flagger-managed clone. Debugging must target
  `gateway-primary-*` pods.
- Compose remains the dev loop, untouched; Swift stays the dev S3.

## Alternatives considered

- **Copying manifests into the fleet repo** — rejected: hides the platform
  work from the portfolio repo and splits change review across repos.
- **ingress-nginx for canary routing** — rejected: the cluster already runs
  Cilium with Gateway API enabled; no reason to add a second data path.
- **Gating on business metrics** — rejected as unattributable (above).
