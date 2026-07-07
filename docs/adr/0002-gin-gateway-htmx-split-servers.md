# ADR 0002: gin gateway with HTMX/html-template UI and separate app/ops servers

## Status

Accepted

## Context

The gateway is the only user-facing component: it serves the browser UI, accepts job submissions, streams progress, and proxies downloads. A SPA frontend would double the toolchain for what is a form-and-status UI.

## Decision

- HTTP framework: **gin** on the app server (`:8080`).
- UI: server-rendered Go `html/template` pages progressively enhanced with **HTMX** (job submission, SSE-driven status updates). Templates and static assets are embedded in the binary via `go:embed`.
- A second, separate HTTP server on `:9090` ("ops") exposes `/healthz` and `/readyz`, so probes and future internal endpoints never share a listener, middleware chain, or exposure surface with user traffic.

## Consequences

- One binary, no Node toolchain, trivially embeddable in a distroless image.
- Probes keep working even if app middleware (sessions, rate limits) misbehaves, and the ops port is never published beyond the compose network in real deployments.
- HTMX limits UI ambition; acceptable for a submit-poll-download flow.

## Alternatives considered

- **SPA (React/Vue) + JSON API** — rejected: second build system and CORS/auth surface for marginal UX gain.
- **Single server with `/healthz` on the app port** — rejected: probe traffic entangled with user middleware and public exposure.
- **stdlib `net/http` only** — workable, but gin's routing/binding/middleware conventions are worth the single dependency.
