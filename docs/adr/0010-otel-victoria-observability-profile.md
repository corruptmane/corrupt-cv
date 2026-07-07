# ADR 0010: OTel wiring with a collector-fronted Victoria stack as an optional compose profile

## Status

Accepted (service-side wiring implemented)

## Context

The system spans three services and a message bus; debugging a job requires correlating one request across all of them. Observability infra should be present in dev but must not tax the default `just up` experience.

## Decision

- Services emit **OpenTelemetry** (traces, metrics, logs) to a single **OTel Collector**, which fans out to **VictoriaMetrics** (metrics), **VictoriaLogs** (logs), and **VictoriaTraces** (traces), with **Grafana** provisioned against all three plus a `cvgen` dashboard. The whole stack lives behind the compose **`observability` profile**; `just up-obs` sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` on the app services, and an empty/unset endpoint means telemetry is a **true no-op** (no exporters constructed).
- Trace context crosses NATS via **manual `traceparent` propagation in message headers** — there is no auto-instrumentation for the JetStream publish/consume boundary, so publishers inject and consumers extract explicitly (lowercase header keys; Go bypasses `nats.Header`'s MIME canonicalization to match Python's case-sensitive extraction).
- Span vocabulary shared across languages: `publish cv.{event}` (PRODUCER) and `consume …` (CONSUMER) with `messaging.system=nats`, `messaging.destination.name`, `cvgen.job_id` attributes; worker child spans `llm.generate`, `typst.render`, `s3.put`. Gateway HTTP/DB/Valkey spans come from `otelgin`/`otelpgx`/`valkeyotel`.
- Business metrics from the gateway's events consumer: `cvgen.jobs.total` (counter, `status` attr) and `cvgen.job.duration` (histogram, seconds, end-to-end), recorded exactly once per job via the store's transition guard. VictoriaMetrics runs with `-opentelemetry.usePrometheusNaming`, so PromQL sees `cvgen_jobs_total` / `cvgen_job_duration_seconds_*`.
- Logs stay structured JSON on stderr in every service; when telemetry is on they are additionally bridged to OTLP (Go: slog fanout handler + otelslog; Python: a structlog processor emitting via the OTel logs API) with automatic trace correlation.

## Consequences

- One OTLP endpoint from the app's perspective; backends are swappable behind the collector.
- The Victoria stack is lighter than Prometheus+Loki+Tempo at this scale and matches the intended production stack, so dashboards carry over.
- Manual propagation is a per-publish/per-consume discipline; the shared libs centralize it so services can't forget.

## Alternatives considered

- **Prometheus + Loki + Tempo** — rejected: heavier, and diverges from the target production stack.
- **Direct-to-backend exporters (no collector)** — rejected: three exporter configs per service and no single place for batching/retry/routing.
- **Observability always-on in the core stack** — rejected: five extra containers for people who just want to render a CV.
