# 0002. HTMX server-rendered UI on the Gin gateway

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The `gateway` (Go/Gin, port `8080`) is the only user-facing surface and already
owns three jobs: accept the per-job request, hold the BYO API key in Valkey, and
project bus results into Postgres as the **sole Postgres writer**. It needs a UI
that lets a user submit a job and watch its status progress through the
`queued -> structured -> completed` (or `failed`) lifecycle in real time.

Forces:
- This is a **platform-engineering showcase**. The interesting surface is the
  infra/contracts/CI/observability, not a rich client. UI complexity should be
  near zero and add no new build pipeline.
- The status signal is already on the bus: per-job subjects
  `cv.{jobID}.{requested,structured,completed,failed}` on JetStream stream `CV`.
  The UI just needs to tail one job's subject and re-render.
- Single deployable: the gateway binary must be self-contained for the
  docker-compose vertical slice (`services/gateway/Dockerfile`), with no extra
  static-asset host or CDN.
- Live updates must be push, not poll, to keep the demo honest about the
  event-driven design.

## Decision

Server-render the UI from the Gin gateway using **HTMX**, with **Server-Sent
Events (SSE)** for live status. No Node, no SPA, no client build step.

- HTML lives in `services/gateway/web/templates/*.html`
  (`index.html`, `status.html`, `fragments.html`); the Gin server parses them via
  `template.ParseFS(web.FS, "templates/*.html")`.
- htmx (+ the SSE extension) load from a **CDN** in the page `<head>`; only our
  `app.css` is vendored under `web/static` and embedded with `//go:embed` in
  `web/web.go`. Templates are embedded too, so the binary still ships the UI.
- Live status uses SSE: the browser opens `GET /generations/:id/events`, the handler
  (`internal/httpapi/sse.go`) sets `Content-Type: text/event-stream` and
  `X-Accel-Buffering: no`, seeds the **current DB state** via `Store.Get`, then
  live-tails the job. Each event re-renders the `status` fragment server-side and
  is pushed with `c.SSEvent("status", html)`; the stream closes on a terminal
  event.
- The tail is an **ephemeral NATS consumer**: `Bus.JobEvents` creates a JetStream
  `OrderedConsumer` with `FilterSubjects: ["cv.{jobID}.>"]`. One consumer per open
  browser tab, torn down (`cc.Stop()`) when the connection closes. The limits-
  retention `CV` stream is what lets these ephemeral consumers coexist with the
  durable `ai-processor`, `cv-generator`, and `gateway-persist` consumers.

## Alternatives considered (with why-not for each)

- **React (or any) SPA + JSON API.** Adds a Node toolchain, a separate build and
  asset-hosting story, client-side state/routing, and a second language runtime —
  all cost with no payoff for a portfolio whose value is the platform. Rejected.
- **Polling a status endpoint (HTMX `hx-trigger="every 2s"`).** Simpler than SSE
  but contradicts the event-driven thesis, adds latency and load, and wastes the
  fact that the signal is already a live subject (`cv.{jobID}.>`). Rejected in
  favor of push.
- **WebSockets.** Bidirectional and heavier than needed; status flow is one-way
  server->browser. SSE over plain HTTP is sufficient, proxy-friendly, and
  auto-reconnects. Rejected.
- **Durable per-tab consumer.** Would leak consumer state on the `CV` stream for
  every closed tab. The ephemeral `OrderedConsumer` is created and `Stop()`-ed
  per connection. Rejected.
- **Vendoring htmx into the binary** (the original v1 choice). Self-contained and
  offline, but pins the version and bloats the embed. Switched to the **CDN** for
  simpler updates; the trade-off is a runtime network fetch on the page (and a CSP
  allowance). `app.css` stays vendored since it is ours.

## Consequences (positive and negative/trade-offs)

Positive:
- One language (Go) and one deployable for the whole front door; no JS build in CI.
- Rendering stays server-side and reuses the gateway's existing view layer
  (`internal/httpapi/view.go`), so DB-projected status and live bus status render
  through the same `renderStatus` path — no client/server status drift.
- SSE seeds from Postgres then tails NATS, so a late-joining or reloaded tab still
  shows correct current state, not just future events.
- Templates + `app.css` stay embedded; htmx comes from the CDN (one fewer vendored
  asset to track, at the cost of a runtime fetch).

Negative / trade-offs:
- SSE holds an open HTTP connection and an ephemeral NATS consumer per tab; many
  concurrent viewers cost goroutines and consumers (fine at v1 scale, a scaling
  note for later).
- Server-rendered HTML couples markup to the Go templates; richer interactivity
  would push back toward client-side code.
- Minimal client JS (`sse.js`) is still hand-maintained rather than typed/tested
  like the Go code.

## Sets up

Keeping the UI inside the single Gin deployable with no separate frontend build
simplifies the deferred **Kubernetes manifests / Flux GitOps** and
**progressive-delivery (canary)** layers: there is one rollout unit to ship and
shift traffic across, not a web app plus an API plus a static-asset pipeline.
