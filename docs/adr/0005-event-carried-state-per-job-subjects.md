# ADR 0005: Event-carried state on per-job subjects

## Status

Accepted

## Context

A job flows gateway → ai-processor → cv-generator, and the browser needs live progress over SSE. The state of a job had to be derivable somewhere: either services report status to a central store/channel, or the events themselves carry the state.

## Decision

**Event-carried state** on per-job subjects: every lifecycle event is published to `cv.{job_id}.{requested|structured|rendered|failed}` in the `CV_EVENTS` stream. Events carry the full payload the next stage needs; replaying a job's subject reconstructs its state.

Supporting choices:

- **Limits retention, 24h `MaxAge`** on `CV_EVENTS`: events are facts, not work items, and multiple readers (workers, gateway persistence, any number of SSE consumers) consume the same messages.
- A **durable multi-filter consumer `GATEWAY_EVENTS`** feeds the gateway's persistence path, projecting events into Postgres for job history.
- Each SSE connection gets an **ephemeral ordered consumer** on `cv.{job_id}.>` with `DeliverAll`, so a client connecting mid-job replays the history and then tails live events. Disconnects clean themselves up.
- Failure handling: worker consumers use `MaxDeliver: 3` with backoff; exhausted deliveries surface as `MAX_DELIVERIES` advisories which the gateway turns into failed jobs; a **10-minute sweeper** marks jobs stuck without terminal events as failed.

## Consequences

- No status table writes from workers, no cross-service RPC; the stream is the source of truth for 24h and Postgres is the projection for history.
- Ephemeral ordered consumers make SSE fan-out cheap but are single-replica-friendly only; multi-replica SSE needs a fan-out layer (roadmap).
- 24h retention bounds replay: jobs older than a day exist only in Postgres.

## Alternatives considered

- **Separate status channel/subject updated by each service** — rejected: two sources of truth (status vs events) that can disagree; extra writes for no reader benefit.
- **DLQ stream for poisoned events** — rejected for v1: `MAX_DELIVERIES` advisories + failed-job projection give the same observability without another stream to manage; revisit if manual reprocessing becomes a need (roadmap).
- **WorkQueue or Interest retention** — rejected: both delete messages once consumed/acked, destroying the replay that SSE and the persistence consumer depend on; WorkQueue additionally forbids the multiple overlapping consumers this design requires.
