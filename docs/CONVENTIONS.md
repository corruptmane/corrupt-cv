# Integration conventions

The single source of truth for the contract **between** services. Every service
MUST adhere to this; it is what keeps the gateway (Go) and the two Python
workers coherent without sharing code beyond the generated protobuf stubs.

## Services & ports

| Service        | Lang          | Port(s)                     | Role                                            |
|----------------|---------------|-----------------------------|-------------------------------------------------|
| `gateway`      | Go / Gin      | `8080` app · `9090` ops     | HTMX UI, SSE, PDF download; **sole Postgres writer** |
| `ai-processor` | Python 3.13   | `8081` ops                  | `requested` → AI → `structured`                 |
| `cv-generator` | Python 3.13   | `8082` ops                  | `structured` → Typst PDF → `completed`          |
| `migrate`      | Go (one-shot) | —                           | applies DB migrations, then exits               |
| `postgres`     | —             | `5432`                      | generations table                               |
| `valkey`       | —             | `6379`                      | transient BYO API keys                          |
| `nats`         | —             | `4222` / `8222` mon         | JetStream                                        |
| `localstack`   | —             | `4566`                      | S3-compatible object store (local)              |
| `otel-collector`| —            | `4317` gRPC / `4318` HTTP   | OTLP **traces** ingest                          |
| `victoriametrics`| —           | `8428`                      | metrics TSDB (**scrapes** the ops ports)        |
| `victorialogs` | —             | `9428`                      | logs                                            |
| `victoriatraces`| —            | `10428`                     | traces                                          |
| `grafana`      | —             | `3000`                      | dashboards over VM/VL/VT                         |
| `vector`       | —             | —                           | ships container stdout → VictoriaLogs            |

The **ops** port on each service serves `/livez`, `/readyz`, and `/metrics`
(Prometheus). The gateway runs it as a *separate* HTTP server so operational
traffic never mixes with app traffic.

## Environment variables (canonical names)

| Var | Example (in-compose) | Used by |
|-----|----------------------|---------|
| `NATS_URL` | `nats://nats:4222` | all |
| `NATS_STREAM` | `CV` | all |
| `POSTGRES_DSN` | `postgres://cv:cv@postgres:5432/cv?sslmode=disable` | gateway, migrate |
| `VALKEY_URL` | `redis://valkey:6379/0` | gateway, ai-processor |
| `S3_ENDPOINT` | `http://localstack:4566` | gateway, cv-generator |
| `S3_REGION` / `S3_BUCKET` | `us-east-1` / `cv-pdfs` | gateway, cv-generator |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | `test` / `test` | gateway, cv-generator |
| `S3_USE_PATH_STYLE` | `true` | gateway, cv-generator |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | all (**traces only**) |
| `OTEL_SERVICE_NAME` | `gateway` / `ai-processor` / `cv-generator` | all |
| `OTEL_RESOURCE_ATTRIBUTES` | `deployment.environment=local,service.version=0.1.0` | all |
| `LOG_LEVEL` | `info` | all |
| `SECRET_TTL_SECONDS` | `300` | gateway, ai-processor |
| `GATEWAY_HTTP_ADDR` | `:8080` | gateway (app) |
| `GATEWAY_OPS_ADDR` | `:9090` | gateway (ops) |
| `MODELS_CONFIG_PATH` | `/config/models.yaml` | gateway |
| `HEALTH_ADDR` | `:8081` / `:8082` | python workers (ops) |

## NATS JetStream

- **Stream** `CV`, subjects `cv.>`, **limits** retention (so multiple consumers
  and ephemeral SSE consumers can all read; max-age ~1h, file storage).
- **The gateway is the sole stream owner** — it `CreateOrUpdate`s the stream on
  startup. Workers never create it; they **poll `stream_info` with bounded
  backoff** and fail fast if it never appears.
- **Subjects** `cv.{jobID}.{type}`, `type ∈ {requested,structured,completed,failed}`.
- **Durable consumers** (filtered): `ai-processor`→`cv.*.requested`,
  `cv-generator`→`cv.*.structured`, `gateway-persist`→`cv.*.{structured,completed,failed}`.
- **SSE**: per-request **ephemeral** ordered consumer, filter `cv.{jobID}.>`,
  **DeliverAll** (replay then live-tail) so a terminal event landing before the
  browser connects is never missed.
- **Payloads** are protobuf **binary** (`cv.v1`): `requested`→`GenerationRequest`,
  `structured`→`CVStructured`, `completed`→`CVCompleted`, `failed`→`CVFailed`.
- **Trace context**: publishers inject W3C `traceparent` into NATS **headers**;
  consumers extract to continue the trace.

## Secret handling (BYO key)

- Gateway writes the submitted key to Valkey at `apikey:{jobID}` with
  `SECRET_TTL_SECONDS` TTL (Go `go-redis`), then publishes `requested` (key NOT
  in payload).
- ai-processor does a single **GETDEL** `apikey:{jobID}` (Python `valkey`) to
  consume it.
- The key is never persisted to Postgres, never put on a JetStream payload,
  never logged. Provider/model travel on the bus; the key never does.

## Object storage

- Rendered PDFs live at S3 key `pdfs/{jobID}.pdf`. `cv-generator` writes
  (OpenDAL); `gateway` streams it to the browser (aws-sdk-go-v2).

## Database ownership & migrations

- Only the gateway writes Postgres. Workers are stateless: they react to bus
  messages and report results as new bus messages; the `gateway-persist`
  consumer projects those into the `generations` table.
- Status lifecycle: `queued → structured → completed`, or `→ failed`.
- **Migrations run as a separate one-shot step** (`cmd/migrate`, a compose
  service the gateway `depends_on … service_completed_successfully`) — never on
  gateway startup.

## Model registry

- Selectable models are config-driven: `config/models.yaml` maps
  `provider → [{id, label, default}]`, loaded by the gateway (mounted, editable
  without a rebuild).
- The UI renders a model dropdown that updates per provider via `GET /models`
  (HTMX). On submit the gateway validates `(provider, model)` and falls back to
  the provider default for an unknown id.

## Observability

- **Traces** are pushed via OTLP/gRPC to the collector → VictoriaTraces.
- **Metrics** are **pulled**: each service exposes Prometheus `/metrics` on its
  ops port and VictoriaMetrics scrapes it (see `observability/victoriametrics-scrape.yml`).
- **Logs** are structured JSON to stdout (Go `slog`; Python `structlog`) shipped
  by Vector to VictoriaLogs. Fields: `time`, `level`, `msg`, `service`, plus
  `job_id`/`trace_id`/`span_id` in scope.
- **Instrumentation**: gateway uses otelgin (HTTP), otelpgx (Postgres), otelaws
  (S3), redisotel (Valkey) + manual NATS spans; the Python workers use manual
  spans for NATS consume, Valkey GETDEL, and the OpenDAL write.

## Operational endpoints (every service)

- `GET /livez` → 200 while the process is up.
- `GET /readyz` → 200 when dependencies are reachable (gateway: Postgres +
  Valkey + NATS; workers: NATS stream bound), else 503.
- `GET /metrics` → Prometheus exposition (scraped by VictoriaMetrics).
