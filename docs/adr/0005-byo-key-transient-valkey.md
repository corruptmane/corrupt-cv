# 0005. BYO API key handling: transient in Valkey, never persisted

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The platform is bring-your-own-key (BYO): the user submits their own provider
API key (OpenAI / Anthropic / Gemini) with each generation request, and the
`ai-processor` uses it to drive the PydanticAI `Agent`. A raw provider secret
therefore enters the system on every request and must reach exactly one
consumer, once.

Forces in tension:

- **Choreography is async and durable.** Work flows over NATS JetStream subjects
  `cv.{jobID}.{requested,structured,completed,failed}` on stream `CV`, which uses
  *file storage* with limits retention (`max-age ~1h`). Anything placed on a
  payload is persisted to disk and replayable by every consumer, including the
  per-tab ephemeral SSE consumer that tails `cv.{jobID}.>`.
- **Two languages, two processes.** The Go gateway accepts the request; the
  Python `ai-processor` (a separate process, reached only via the bus) needs the
  key. They share no code beyond generated protobuf stubs, so the secret has to
  cross a process boundary.
- **Audit/blast-radius.** The gateway is the sole Postgres writer and projects
  every bus event into the `generations` table; logs are structured JSON shipped
  by Vector to VictoriaLogs. A leaked secret in either store would be durable and
  widely fanned-out.
- **Keyless providers exist.** Ollama and `PROVIDER_TEST` (TestModel) run with
  no key, so the mechanism must treat "no secret" as a first-class, no-op case.

## Decision

Move the secret **out of band** from the event payload, through a transient
side-channel keyed by job id:

- The gateway writes the submitted key to Valkey at `apikey:{jobID}` with a TTL
  of `SECRET_TTL_SECONDS` (300s in-compose), then publishes `cv.{jobID}.requested`
  carrying only the provider/model — never the key
  (`services/gateway/internal/secrets/secrets.go`, `Store.Put`). An empty key
  (keyless provider) is a no-op write.
- The `ai-processor` consumes the key with a single atomic **GETDEL**
  `apikey:{jobID}` (`services/ai-processor/ai_processor/secrets.py`,
  `SecretStore.take`). GETDEL guarantees single-use: fetch and delete in one
  round-trip, so a replayed `requested` message cannot re-read the secret.
- The key is **never** written to Postgres, **never** placed on a JetStream
  payload, and **never** logged. Provider and model travel on the bus; the key
  does not.

Valkey is configured purely as transient store: `--save "" --appendonly no`
(no RDB snapshot, no AOF), so the secret is in-memory only and the TTL bounds
its lifetime even if it is never consumed (e.g. the worker crashes).

## Alternatives considered (with why-not for each)

- **Key on the `requested` protobuf payload (`GenerationRequest`).** Rejected:
  JetStream persists messages to file storage and retains them (~1h); the limits
  stream is multi-consumer and the ephemeral SSE consumer can replay
  `cv.{jobID}.>` to the browser. The secret would be durable, fanned-out, and
  recoverable from disk. This is the failure mode the whole ADR exists to avoid.
- **Server-side managed keys (platform holds provider credentials).** Deferred,
  not rejected on merit — it removes BYO entirely and pulls in billing/metering
  and key custody. Belongs with the deferred Stripe billing + auth work, not the
  v1 vertical slice.
- **Encrypt the key and put the ciphertext on the bus.** Rejected for v1: adds a
  KMS/key-management dependency and still persists ciphertext to JetStream for
  ~1h. Valkey + TTL achieves "transient, single-use" with far less machinery.
- **Pass the key inline (gateway calls the provider itself).** Rejected: breaks
  the async choreography and the gateway/worker separation — the gateway would
  need provider SDKs and PydanticAI, defeating the stateless-worker design.

## Consequences (positive and negative/trade-offs)

Positive:

- The secret has a single, narrow path: gateway `SET` -> Valkey -> worker
  `GETDEL`. It cannot leak into the durable stores (Postgres, JetStream,
  VictoriaLogs) by construction.
- Single-use is enforced atomically by GETDEL, so message replay (a normal
  JetStream/retry event) never re-exposes the key.
- TTL caps exposure even on the unhappy path; with no AOF/RDB the value never
  hits disk.
- Keyless providers (Ollama, `PROVIDER_TEST`) fall out naturally: empty key =>
  no write => `take` returns `None`. The full pipeline runs in CI/demos with no
  secret in play.

Negative / trade-offs:

- Adds Valkey as a required dependency on the request path for both the gateway
  and the `ai-processor` (`VALKEY_URL`), and a new failure mode if it is down.
- Tight coupling to timing: if processing is delayed past `SECRET_TTL_SECONDS`
  the key expires and the job must fail with a "key expired" error rather than
  silently proceeding. TTL must be tuned against realistic LLM latency.
- At-most-once delivery of the secret: a worker crash *after* GETDEL but *before*
  using the key loses it irrecoverably (the user must resubmit). This is an
  accepted cost of guaranteeing single-use.

## Sets up

Establishes the trust boundary that future server-side managed keys and Stripe
billing will build on: when the platform later holds provider credentials, the
same out-of-band, never-persisted, never-logged discipline (and the
gateway/worker split) carries over — only the source of the key changes.
