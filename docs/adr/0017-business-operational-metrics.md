# 17. Business and operational metrics across all three services

Date: 2026-08-26

## Status

Accepted

## Context

ADR 0010 shipped traces and logs everywhere but left metrics lopsided: the
gateway emitted HTTP metrics plus two business instruments
(`cvgen.jobs.total`, `cvgen.job.duration`), while both Python workers —
where the LLM money and the render time are spent — produced none.
`cv_shared.setup_otel()` wired only tracer and logger providers. Nothing
measured the funnel from form submission to download, provider behavior,
render/storage internals, or queue depth, and VictoriaMetrics had no data
to answer "why did completion rate drop" without spelunking logs.

Scope decided with the owner: metric **emission only** in this pass — no
dashboard or alert-rule changes; those follow once the series have been
observed for a while.

## Decision

Both Python signals now flow through one `MeterProvider`
(`PeriodicExportingMetricReader` → OTLP push) built inside the same
endpoint-gated `setup_otel()` as the tracer/log providers, so the
telemetry-off contract of ADR 0010 is preserved unchanged: unset
`OTEL_EXPORTER_OTLP_ENDPOINT` still means every instrument is a true
no-op in both languages.

New instruments follow the conventions ADR 0010 established, now binding:

- **Namespace `cvgen.`**; counters carry an explicit `.total` suffix in
  the OTel name (`cvgen.jobs.created.total` → PromQL
  `cvgen_jobs_created_total` under `-opentelemetry.usePrometheusNaming`).
  Histograms declare a unit (`s`, `By`) so VM renders `_seconds_*` /
  `_bytes_*`.
- **Low-cardinality labels only**: `status`, `stage`, `provider`,
  `model_key` (bounded by the fixed catalog), `event`, `outcome`,
  `reason`, `type`, `consumer`. Never `job_id`, `visitor_id`, or subjects.
- **Explicit buckets** on latency histograms sized to their real spread
  (LLM calls 0.25–120 s, compiles 10 ms–5 s, uploads 5 ms–5 s); page and
  byte histograms get buckets matching plausible CV sizes. Defaults make
  p50/p95 useless at these scales.
- **Python instruments are module-level** (`get_meter(...)` before
  setup), deferring to the real provider through the SDK's proxy meter —
  the same idiom the tracers already use.

Inventory (owner: emitting service):

| Metric | Kind | Labels | Where |
| --- | --- | --- | --- |
| `cvgen.jobs.created.total` | counter | model_key | gateway create handler |
| `cvgen.jobs.rejected.total` | counter | reason | gateway validation |
| `cvgen.profiles.saved.total` | counter | — | gateway profile save |
| `cvgen.jobs.downloads.total` | counter | — | gateway download |
| `cvgen.download.bytes` | histogram By | — | served PDF size |
| `cvgen.sse.streams.total` / `cvgen.sse.active` | counter / gauge | — | SSE streams opened / open |
| `cvgen.jobs.swept.total` / `cvgen.jobs.poisoned.total` | counter | event | sweeper / MAX_DELIVERIES advisory |
| `cvgen.consumer.pending` / `cvgen.consumer.ack_pending` | gauge | consumer | sweep tick, all three durables |
| `cvgen.messages.consumed.total` | counter | event, outcome | shared consume loop (ack/term/nak) |
| `cvgen.messages.handle.duration` | histogram s | event | shared consume loop |
| `cvgen.messages.published.total` | counter | event, outcome | shared publish helper (per attempt) |
| `cvgen.messages.publish.retries.total` | counter | event | transient publish retries |
| `cvgen.llm.attempts.total` | counter | provider, model_key, outcome | per agent run |
| `cvgen.llm.request.duration` | histogram s | provider | per LLM call |
| `cvgen.llm.tokens.total` | counter | provider, type | input/output usage |
| `cvgen.processing.failures.total` | counter | reason | ai-processor `_fail` |
| `cvgen.render.compiles.total` / `.duration` | counter / histogram s | outcome / — | typst compile site |
| `cvgen.render.pages` | histogram | — | recorded even when over limit |
| `cvgen.rendering.failures.total` | counter | reason | cv-generator `_fail` |
| `cvgen.storage.put.duration` / `.bytes` | histogram s / By | — | PDF upload |

The failure-reason vocabularies are closed sets defined next to the
user-safe error constants: processing failures use
`api_key_missing | unknown_model | invalid_input | auth | bad_request |
bad_output | unavailable | credits_exhausted | internal`; rendering uses
`invalid_input | render_failed | page_limit`; gateway rejections use
`empty_description | unknown_model | missing_api_key | no_profile |
job_too_long | career_too_long | incomplete_profile`. Every `_fail` call
site must pass a machine reason alongside the human copy, so alerting can
key on reasons that never change wording.

Division of labor: workers count what happens inside them (LLM, render,
storage, per-message outcomes); the gateway owns anything needing a
pipeline-wide view — consumer backlog gauges are refreshed from its sweep
tick because it provisions all three durables anyway (ADR 0004), keeping
the workers free of JetStream admin API calls.

Go instrument creation goes through small fallback helpers
(`internal/telemetry/metrics.go`) that substitute a no-op instrument on
creation error instead of the previous warn-and-continue pattern, which
left nil instruments that would panic on first use — a rejected name must
degrade to silence, not a crash loop.

## Consequences

- The full pipeline becomes queryable in PromQL with zero infra change:
  conversion funnel (`created/rejected/consumed/rendered/downloads`),
  spend drivers (`llm_tokens_total by provider`), and queue health
  (`consumer_pending`) all come from standard env-driven OTLP push.
- Counters record only completed terminal actions: a failed ack/term/nak
  propagates uncounted, so `messages_consumed_total` never overstates
  handled work. Publish counting lives in `publish_event` (per attempt,
  outcomes ok/error), so direct `_fail` publishes are counted too;
  retries get their own series rather than inflating published counts.
- Dashboards/alerts remain untouched by design; the first pass is
  observing which series earn rules.
- Per-attempt token counting trusts the provider-reported usage; fake and
  providers omitting usage simply emit nothing.

## Alternatives considered

- **Prometheus scrape endpoints per service** — rejected: contradicts the
  collector-fronted push topology of ADR 0010 and adds discovery config
  for three services already exporting everything else via OTLP.
- **Metrics derived from job events after the fact** (projection-side
  counters for LLM/render internals) — rejected: stage-internal details
  like token counts and compile durations never cross the stream; they
  must be recorded where they happen.
- **High-cardinality labels** (job_id) for per-job debugging — rejected:
  unbounded series cardinality in VictoriaMetrics; traces already serve
  per-job questions via `cvgen.job_id`.
