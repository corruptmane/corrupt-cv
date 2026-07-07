# ADR 0006: BYO API key handoff via Valkey SET EX + GETDEL

## Status

Accepted

## Context

Users bring their own LLM API key per job. The key must reach ai-processor exactly once and must never be persisted: not in NATS (24h replayable stream), not in Postgres (job history), not in logs.

## Decision

The gateway writes the key to **Valkey** as `cv:apikey:{job_id}` with `SET EX 900` (15-minute TTL) and publishes the job event *without* the key. ai-processor claims it with an atomic **`GETDEL`** — the key ceases to exist the moment it is read. If a JetStream redelivery occurs *after* a successful claim, the key is gone and the job fails; in-process retries inside ai-processor (which still holds the key in memory) compensate for transient provider errors, so a redelivery-after-claim genuinely means the first attempt died mid-flight.

The `fake/canned-cv` catalog entry requires no key at all, so the whole pipeline is testable without this path.

## Consequences

- Key lifetime is bounded by min(TTL, first claim); nothing durable ever contains it, and a crashed worker leaks nothing past 15 minutes.
- Accepted trade-off: a worker that claims the key and then crashes fails the job — the user resubmits with the key again. This is the price of exactly-once semantics for a secret.
- Valkey becomes a hard runtime dependency of job submission and ai-processor.

## Alternatives considered

- **Key inside the NATS event** — rejected: persisted in a replayable stream for 24h, visible to every consumer.
- **Key in Postgres with a cleanup job** — rejected: durable persistence of a secret plus cleanup machinery.
- **GET + DEL (non-atomic)** — rejected: race window where two redeliveries both read the key.
- **Envelope encryption of the key in the event** — rejected for v1: key management complexity without removing the fundamental persistence problem.
