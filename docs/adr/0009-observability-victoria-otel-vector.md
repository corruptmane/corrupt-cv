# 0009. Observability: OpenTelemetry into the full Victoria stack

- **Status:** Accepted
- **Date:** 2026-06-17 (updated 2026-06-18: metrics pull, ops endpoints, instrumentation)

## Context and forces

This is a platform-engineering showcase: the value is the infra/contracts/CI and
**observability** around a working product. The pipeline is an async choreography
across three services in two languages — `gateway` (Go/Gin), `ai-processor` and
`cv-generator` (Python 3.13) — talking only over NATS JetStream
(`cv.{jobID}.{type}`). A single request fans out `requested → structured →
completed` across process boundaries, so the only way to answer "what happened to
this job, and where did it spend its time" is **distributed tracing with context
propagated across the bus**, plus metrics and correlatable logs.

Forces:

- **Three signals, one correlation key** (`trace_id`/`span_id`/`job_id`).
- **Vendor-neutral instrumentation** (OTLP), backend swappable.
- **Homelab-friendly, low-overhead backends** — the author runs a Victoria stack.
- **Telemetry must never gate the product** — the pipeline runs with the backends
  absent (CI, demos, bare host).

## Decision

**Instrument with OpenTelemetry and land all three signals in the Victoria stack,
with Grafana as the single pane of glass.** Each signal takes the path that fits
it best:

- **Traces → push (OTLP/gRPC) → collector → VictoriaTraces.** Services export
  spans to `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`, tagged with
  `OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES`. The collector
  (`observability/otel-collector-config.yaml`) forwards via `otlphttp/traces` to
  VictoriaTraces. **Trace context crosses NATS** as W3C `traceparent` in message
  headers (`inject_headers`/`extract_context`), so one job is one trace across all
  three services.
- **Metrics → pull (Prometheus scrape).** Each service exposes Prometheus
  `/metrics` on its **ops port** (gateway `:9090`, workers `:8081`/`:8082`);
  VictoriaMetrics scrapes them (`observability/victoriametrics-scrape.yml`). Go
  uses the OTel Prometheus exporter; Python uses `PrometheusMetricReader` served by
  `cv_worker/ops.py`. The collector no longer touches metrics.
- **Logs → stdout → Vector → VictoriaLogs.** Services write structured JSON to
  stdout (Go `slog`; Python **structlog**, `cv_worker/log.py`), fields
  `time`/`level`/`msg`/`service` + `trace_id`/`span_id`/`job_id` in scope. Vector
  (`observability/vector.yaml`) tails container stdout via the Docker socket and
  ships to VictoriaLogs' Elasticsearch-bulk endpoint.
- **Library instrumentation.** The gateway wires otelgin (HTTP), **otelpgx**
  (Postgres), **otelaws** (S3), and **redisotel** (Valkey) plus manual NATS spans;
  the Python workers add manual spans for NATS consume, the Valkey GETDEL, and the
  OpenDAL write.

Telemetry is best-effort: exporters are built lazily and an unreachable
collector/registry simply drops data.

## Alternatives considered (with why-not for each)

- **Prometheus + Loki + Tempo + Jaeger.** The mainstream spread — four backends to
  run and wire, heavier footprint. The Victoria stack covers all three signals with
  a lighter operational cost and a query surface the author already runs.
- **Push metrics via OTLP → collector → remote-write (the original v1 design).**
  Reconsidered and replaced by **pull**: the services already run an ops HTTP server
  for `/livez`/`/readyz`, so exposing `/metrics` there is nearly free; pull is
  Prometheus-native, gives a built-in target up/down signal, and maps directly to
  Kubernetes `ServiceMonitor`s in the deferred GitOps layer. Push remains fine for
  short-lived jobs, but these are long-running services.
- **Routing logs through the OTel Collector.** Rejected: stdout-JSON + Vector is
  the twelve-factor path, keeps containers logging when OTLP is down, and lets
  Vector pick up infra-container lines an SDK pipeline never sees.

## Consequences (positive and negative/trade-offs)

Positive:

- **End-to-end traces** of a job across all three services, with the otelpgx/
  otelaws/redisotel spans nested under each service's work.
- **Three signals correlate** on `trace_id`/`span_id`/`job_id` in Grafana.
- **Prometheus-native metrics** with target up/down, ready for k8s ServiceMonitors.
- **Resilient by construction** — the product runs with telemetry down.

Negative / trade-offs:

- **Two ingest models** (push traces via collector, pull metrics via VM scrape)
  plus the Vector log path (mounts the Docker socket read-only).
- **Silent telemetry loss** — best-effort drops data quietly rather than loudly.
- **VictoriaTraces query API** is Jaeger-compatible, not OTel-native.

## Sets up

- A backend-swap seam for the deferred Kubernetes/Flux layer: the same OTLP traces,
  Prometheus scrape, and Vector pipeline retarget to a managed/clustered Victoria
  without code changes; `/metrics` + `/readyz` map straight onto ServiceMonitors and
  readiness probes.
- The trace + metric foundation that later **progressive delivery** (canary
  analysis, deferred) needs for its health gates.
