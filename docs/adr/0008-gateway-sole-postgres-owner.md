# 0008. Gateway as the sole Postgres owner; stateless workers

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The pipeline is an async choreography over NATS JetStream (stream `CV`,
subjects `cv.{jobID}.{type}`). A request fans out across three services: the
`gateway` (Go/Gin), the `ai-processor` and the `cv-generator` (both Python).
Status of a generation (`queued → structured → completed`, or `→ failed` from
any stage) must be queryable for the SSE UI and the PDF download, which means it
has to land in Postgres (the `generations` table, `0001_init.sql`).

The forces:

- **One writer, one schema.** If every service wrote its own slice of Postgres,
  the `generations` row schema (`internal/store/migrations/0001_init.sql`,
  `queries/generations.sql`) would be co-owned by three codebases in two
  languages, each needing a DSN, a driver, migration access, and sqlc/goose
  parity. That couples deploys and invites write races on the same row.
- **Keep workers stateless.** `ai-processor` and `cv-generator` should be pure
  bus transformers (consume one subject, emit another). That makes them trivial
  to scale, restart, and reason about — no DB connection, no `POSTGRES_DSN`.
- **Single ordering authority.** Status transitions must be linearizable per job.
  A durable consumer over the result subjects gives one in-order projection path.
- **Secret hygiene.** Workers already avoid persistence by design — the BYO key
  lives only in Valkey (`apikey:{jobID}`, `GETDEL`) and is never written to
  Postgres. Fewer DB writers means fewer places that could leak request data.

## Decision

**Only the `gateway` connects to and writes Postgres.** It holds the lone
`POSTGRES_DSN` (per `docs/CONVENTIONS.md`), owns the goose migrations under
`services/gateway/internal/store/migrations/` — applied by a **separate one-shot
`cmd/migrate` step** (a compose service the gateway `depends_on …
service_completed_successfully`), never on startup — and runs the sqlc-generated
queries (`internal/store/db/`).

The Python workers are stateless: they react to bus messages and report results
as **new** bus messages only. The gateway runs a single durable consumer,
**`gateway-persist`**, that filters the result subjects and projects each event
into the `generations` row:

- `gateway-persist` → `FilterSubjects: ["cv.*.structured", "cv.*.completed",
  "cv.*.failed"]` (`internal/bus/bus.go`, `ConsumePersist`), `AckExplicitPolicy`.
- Projection (`queries/generations.sql`): the synchronous POST handler does
  `CreateGeneration` (status `queued`); then on the bus, `cv.*.structured` →
  `MarkStructured`, `cv.*.completed` → `MarkCompleted` (sets `pdf_object_key`),
  `cv.*.failed` → `MarkFailed` (sets `error`).

Workers never touch the table; they emit `CVStructured` / `CVCompleted` /
`CVFailed` protobuf and move on. The PDF itself is in S3 at `pdfs/{jobID}.pdf`;
Postgres only stores the object key.

## Alternatives considered (with why-not for each)

- **Per-service tables (each worker owns its own table).** Rejected: the read
  model the UI needs is one denormalized `generations` row per job; splitting it
  across `ai_results` / `pdf_results` tables forces the gateway to JOIN/poll
  three sources to answer one SSE status, and still requires every Python
  service to carry a Postgres driver, DSN, and migration ownership.
- **Shared DB writes (every service UPSERTs the same `generations` row).**
  Rejected: three writers across two languages racing on one row needs
  cross-service locking or optimistic concurrency, duplicates the sqlc/goose
  toolchain into Python (which today uses neither), and makes "who set this
  field" ambiguous during incident triage.
- **Workers write status, gateway reads only.** Rejected: same multi-writer
  coupling as above, and it would put a stateful dependency back into services
  whose whole point (ADR rationale) is to be replaceable bus transformers.

## Consequences (positive and negative/trade-offs)

Positive:

- **Ownership clarity.** Exactly one service owns the schema, migrations, and
  query layer; the contract for everyone else is the bus (`docs/CONVENTIONS.md`),
  not the table.
- **Stateless, scalable workers.** No `POSTGRES_DSN` in the Python services; they
  scale and restart freely, and a worker outage never corrupts persisted state —
  unacked messages redeliver (`AckExplicitPolicy`).
- **Single, in-order projection.** One durable consumer linearizes status
  transitions per job; the projection is also idempotent-friendly (terminal
  `MarkCompleted`/`MarkFailed` overwrite by `id`).
- **Tighter secret boundary.** One DB writer, and request data lives in one place.

Negative / trade-offs:

- **Persisted status is eventually consistent**, lagging the bus by the
  `gateway-persist` ack cycle. The live SSE path sidesteps this by tailing the
  job's own subjects via an ephemeral consumer (`cv.{jobID}.>`), so the browser
  sees events before/independently of the DB write.
- **The gateway is a write bottleneck and a single point of failure** for
  persistence. Acceptable at v1 scope (one gateway instance); a gateway crash
  pauses projection but loses nothing (limits-retention stream replays on
  restart).
- **Schema changes are gateway-coupled** — a new field a worker emits isn't
  persisted until the gateway adds a migration + query, but that is the intended
  single point of change.

## Sets up

- The clean gateway/worker split is what later lets workers be horizontally
  scaled or canary-rolled (Argo Rollouts/Flagger-style progressive delivery,
  deferred) without touching the data tier.
- A single Postgres owner is the natural seam for the deferred Kubernetes/Flux
  GitOps move (one stateful service, the rest stateless) and for later
  OpenTofu-provisioned managed Postgres.
