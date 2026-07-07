# 0003. Async event choreography over NATS JetStream

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The vertical slice spans three services in two languages: the Go/Gin `gateway`
(HTMX UI, SSE, sole Postgres writer), the Python `ai-processor`
(`requested → structured`), and the Python `cv-generator`
(`structured → completed`). A single CV request fans through all three before
the browser can download a PDF, and the AI step is slow and variable in
latency. We need a transport that:

- decouples the services so each can be deployed, scaled, and failed
  independently (the workers are stateless; only the gateway writes Postgres);
- survives a worker restart mid-flight without dropping a job (durability);
- lets the gateway stream **live** per-job status to one open browser tab over
  SSE without polling Postgres;
- carries versioned `cv.v1` protobuf payloads and propagates W3C trace context
  end-to-end for the Victoria/OTel observability stack;
- never becomes a place where the BYO API key could be persisted.

NATS JetStream is already in the stack (`nats:2.10-alpine`, `--jetstream`,
file store), giving us one durable log plus an ephemeral push-subscription
model — both from a single dependency.

## Decision

Use **event choreography** (no central orchestrator) over a single JetStream
stream `CV` (`NATS_STREAM=CV`, subjects `cv.>`, **LIMITS** retention, FILE
storage, max-age ~1h), with **job-id-first** subjects
`cv.{jobID}.{type}`, `type ∈ {requested,structured,completed,failed}`.

- Each service reacts to the bus and emits the next event:
  `gateway` publishes `cv.{id}.requested` (`GenerationRequest`); `ai-processor`
  consumes and publishes `cv.{id}.structured` (`CVStructured`); `cv-generator`
  consumes and publishes `cv.{id}.completed` (`CVCompleted`); any stage may emit
  `cv.{id}.failed` (`CVFailed`).
- **Durable, type-filtered** consumers do the work:
  `ai-processor` filters `cv.*.requested`, `cv-generator` filters
  `cv.*.structured`, and `gateway-persist` filters
  `cv.*.{structured,completed,failed}` to project status into the `generations`
  table (lifecycle `queued → structured → completed`, or `→ failed`).
- **Ephemeral, ordered** consumers serve SSE: per open tab the gateway subscribes
  with filter `cv.{jobID}.>` and **DeliverAll** (replay the job's events, then
  live-tail) so a terminal event landing before the browser connects is never
  missed — the job-id-first layout makes this a single contiguous prefix match.
- Payloads are protobuf **binary**; W3C `traceparent` (+ `tracestate`) is
  injected into NATS message **headers** by publishers and extracted by
  consumers (`extract_context` in `libs/cvworker/cv_worker/bus.py`) so the trace
  spans the whole pipeline.

The shared helper `Bus` (`libs/cvworker/cv_worker/bus.py`) implements
`connect`/`wait_for_stream`/`publish`/`run_consumer`; the **gateway is the sole
stream owner**, and workers **poll `stream_info` with bounded backoff** (failing
fast if it never appears) rather than creating it.

## Alternatives considered (with why-not for each)

- **Synchronous request/reply** (HTTP/NATS req-rep, gateway awaits each stage):
  couples request lifetime to the slow LLM call, gives no durability across
  restarts, and forces the gateway to hold connections open for the full job.
  SSE live status would have to be bolted on separately. Rejected.
- **A central orchestrator** (a saga/workflow service driving each step):
  adds a stateful component that must itself be made HA and becomes the schema
  bottleneck for every change. The flow is a simple linear pipeline; choreography
  via typed events keeps each service thin and independently shippable, which is
  the whole point of `docs/CONVENTIONS.md` as the only shared contract.
- **Subject-type-first** (`cv.{type}.{jobID}`): a per-tab SSE consumer would need
  a multi-token wildcard (`cv.*.{jobID}`) instead of a clean tail prefix, and the
  natural per-job grouping in the subject space is lost. Job-id-first means
  "everything about one job" is the contiguous range `cv.{jobID}.>`.
- **WORK_QUEUE / INTEREST retention**: a work-queue stream deletes a message once
  any consumer acks it, which breaks fan-out — `ai-processor` and `gateway-persist`
  must both see `structured`, and ephemeral SSE consumers must read freely.
  LIMITS retention lets all of them coexist.

## Consequences (positive and negative/trade-offs)

- **Positive:** services are decoupled and independently deployable; jobs survive
  worker restarts (durable consumers replay un-acked messages — `run_consumer`
  `nak`s on handler failure); one stream serves both durable workers and ephemeral
  SSE; per-job SSE is a trivial `cv.{jobID}.>` tail; trace context flows through
  headers for true end-to-end traces; the bus is BYO-key-safe by construction —
  the key lives only in Valkey at `apikey:{jobID}` (GETDEL), never on a payload.
- **Negative / trade-offs:** eventual consistency — the browser sees status via
  events, not a synchronous result; ordering is per-subject, so cross-stage
  ordering relies on the linear pipeline, not the broker; LIMITS retention +
  max-age means very old jobs age out of the log (acceptable for a portfolio
  slice); no orchestrator means the end-to-end flow is implicit in the subject
  contract and must be kept honest by `docs/CONVENTIONS.md` and the protobuf
  schema; at-least-once delivery requires handlers to tolerate redelivery.

## Sets up

The choreography contract is transport- and deployment-agnostic, so the deferred
Kubernetes + Flux GitOps rollout can scale each consumer independently and run
progressive delivery (canary) on a worker without touching the others. The
typed `cv.v1` event boundary is also where future auth/saved-profiles and
Stripe-billing signals can attach as additional subjects/consumers without
reworking the core flow.
