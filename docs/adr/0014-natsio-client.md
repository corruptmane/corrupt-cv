# ADR 0014: natsio as the Python NATS client

## Status

Accepted

## Context

The Python services originally used nats-py, the reference asyncio client.
The author ships [natsio](https://github.com/corruptmane/natsio) — a
zero-dependency, pure-asyncio NATS client for Python 3.13+ built around the
ADR-37 simplified JetStream API — and this project doubles as a proving
ground for it.

## Decision

cv-shared and both workers migrated from nats-py to natsio 1.0. The
single-authority contract (ADR 0004) is preserved: services bind to
gateway-provisioned entities via `js.stream()` → `stream.consumer(durable)`
and `js.key_value()`, retrying while they don't exist, and never create
anything. Differences that improved the code: `fetch()` returns an empty
list on quiet intervals instead of raising; `publish()` takes `msg_id` as a
first-class kwarg (no hand-built `Nats-Msg-Id` header); `term(reason)`
carries the failure reason into the server advisory; `Headers` implements
`Mapping`, so the OTel trace-propagation carrier worked unchanged;
`KvEntry.value` is guaranteed `bytes`.

natsio requires NATS server ≥ 2.14, so the compose dev server and the
cluster Helm chart both pin 2.14+.

## Consequences

- The pipeline runs the author's own client in production, exercised end to
  end by the compose e2e, the canary loadtester, and cross-service traces.
- The Go gateway stays on nats.go — the polyglot split is deliberate: each
  side uses the idiomatic client for its language.
- Server floor 2.14+ is a hard constraint on every deployment target.

## Alternatives considered

- **Staying on nats-py** — worked, but bind-only pull consumption required
  the legacy `pull_subscribe_bind` API, and the migration removed several
  seams (manual dedup headers, empty-fetch exception handling).
