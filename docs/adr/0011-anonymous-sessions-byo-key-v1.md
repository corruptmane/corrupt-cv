# ADR 0011: Anonymous HMAC-signed cookie sessions; BYO-key-only v1

## Status

Accepted

## Context

The product needs just enough identity to scope profiles, jobs, and downloads to a visitor. Accounts, passwords, and billing would dominate the build without demonstrating anything the pipeline doesn't already show.

## Decision

- **Anonymous sessions**: the gateway issues an opaque visitor id in an **HMAC-signed cookie** (key: `SESSION_SECRET`). No login, no PII beyond what the user types into their profile. All job and download access is scoped to the session's visitor id.
- **BYO-key-only v1**: the service never holds provider credentials of its own; users supply a key per job (handled per ADR 0006), or use `fake/canned-cv` for a keyless demo.
- The platform track — real auth, paid plans/billing, multi-tenant quotas — is **deliberately deferred** to the roadmap (`docs/roadmap.md`).

## Consequences

- Zero credential storage and no auth attack surface beyond cookie forgery, which HMAC signing addresses; rotating `SESSION_SECRET` invalidates all sessions, acceptable in v1.
- Sessions are per-browser: clearing cookies orphans job history. Fine for a demo, unacceptable for paid plans — which is exactly why auth is on the roadmap, not in v1.
- BYO keys sidestep provider billing entirely; the operator's cost surface is compute only.

## Alternatives considered

- **Full auth (email/OAuth) in v1** — rejected: weeks of work orthogonal to the pipeline being showcased.
- **Server-side sessions in Valkey** — rejected: state for state's sake; the cookie payload is one signed id.
- **Operator-owned API keys with quotas** — rejected for v1: turns a demo into a billing/abuse problem.
