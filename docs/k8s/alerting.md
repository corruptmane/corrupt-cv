# Alerting

Four golden-signal alerts watch cvgen in production, defined in
`deploy/k8s/alerting/golden-signals.yaml` as a `VMRule` named
`cvgen-golden-signals` in the `cvgen` namespace — the same CRD the canary
`CanaryRollback` rule uses, since vmalert ingests VMRules from any
namespace. Ingestion differs by producer: the gateway's HTTP metrics are
**pushed via OTLP** through the fleet otel-collector into VMSingle, which
applies Prometheus naming server-side (ADR 0010) — nothing scrapes the app.
The only scrape Flagger needs is the fleet-side `VMPodScrape` pointing
vmagent at flagger's own `/metrics` for the canary rules. For manual
verification, query VMSingle directly at
`http://vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428`
(vmui or `/api/v1/query`) — the same endpoint the canary MetricTemplates
and Flagger's metricsServer use.

Metric names below were verified against live VMSingle:
`http_server_request_duration_seconds_count` / `_bucket` with
`service_name="gateway"`, string-valued `http_response_status_code`
("200"/"500"), and `le` buckets in seconds. The single exception is
`kube_job_status_failed`, which stays unproven until W12 lands the
cvgen-synthetic CronJob and must be re-checked against live series then.

## Gateway 5xx error rate

**Signal** — share of gateway requests answered with 5xx, computed as a
ratio of rates over `http_server_request_duration_seconds_count`
(`http_response_status_code=~"5.."` over all codes). Two windows form one
pair, kept at exactly two rules by owner decision: `[10m] > 2%` warns,
`[5m] > 5%` goes critical — the fast window pages, the slow window gives
earlier, quieter notice of a creeping problem.

**Threshold rationale** — both thresholds sit well below firing on every
blip but far above the noise floor of a healthy service. They are
deliberately looser than Flagger's ≥99% success-rate **canary gate**: that
gate is a deploy-time control deciding whether traffic may shift onto a new
revision; once a revision is fully promoted, nothing else watches it, which
is the gap this pair closes. Denominators carry a `clamp_min(.., 1e-12)`
guard so a fully quiet gateway evaluates to ratio 0 rather than NaN.

**Expected noise** — brief 5xx bumps while a canary rollout probes the new
revision (the windows and `for:` holds absorb short spikes); upstream S3
(`GetObject` PDF downloads) failures surfacing as gateway 5xx; crawler
traffic hitting odd paths.

**First response** — open vmui on the VMSingle endpoint above and compare
the 5xx ratio against the deploy timeline (`kubectl get canaries -w`, or
the flagger events in `kubectl describe canary gateway`). If no rollout is
in flight, check gateway logs in VictoriaLogs
(`victoria-logs-victoria-logs-single-server.monitoring.svc:9428`) filtered
on `service_name="gateway"` for the failing routes before touching
rollbacks.

## Gateway p99 latency

**Signal** — 99th-percentile request duration from
`http_server_request_duration_seconds_bucket` via
`histogram_quantile(0.99, sum by (le)(rate(...[15m])))`; alert when p99
exceeds 1.5s held for 15m.

**Threshold rationale** — deliberately much looser than the 500ms p99 the
Flagger gate enforces during a canary. The gate blocks bad deploys at
deploy time; this alert catches sustained degradation of whatever is
serving production without paging on canary-shift noise or one-off slow
requests. A 15-minute hold means only persistent tail latency pages.

**Expected noise** — long PDF downloads over slow client links stretching
individual requests; canary pods landing on a contended node during a
shift; long-lived SSE responses if otelgin records duration until stream
close — worth confirming against real data the first time it fires.

**First response** — same surfaces as the error-rate section: vmui for the
p99 series (compare primary vs canary pods via `service_instance_id` in an
ad-hoc query), VictoriaLogs for slow-request traces, and the Grafana "CV
Generator" dashboard from the compose observability profile for dev-parity
comparison.

## Synthetic job failures

**Signal** — `sum(increase(kube_job_status_failed{namespace="cvgen",job_name=~"cvgen-synthetic.*"}[2h])) > 0`,
held 5m: any failed run of the synthetic probe within a 2-hour lookback.
The scope deliberately excludes `cvgen-migrate` — migration failures gate
the apps Kustomization (`wait: true`) and surface as a Flux reconciliation
alert instead (ADR 0015).

**Threshold rationale** — zero tolerance with a 2h lookback: the synthetic
job exists precisely to catch a broken pipeline when user traffic is too
quiet to notice, so any failure is signal. The `for: 5m` hold is a small
anti-flap measure riding out a failed Job object being replaced by the next
scheduled run; `increase()` over 2h already smooths single retries within
`backoffLimit`.

**Caveat** — the label set is unproven until W12 lands the CronJob;
re-verify against live series post-W12.

**Expected noise** — retries inside `backoffLimit` counting as multiple
failed runs per occurrence; missed schedules during node maintenance
showing up as gaps rather than failures.

**First response** — `kubectl get jobs -n cvgen` for the failing Job and
its pod logs; then follow the pipeline downstream in VictoriaLogs/NATS the
same way you would for a stuck user job.

## Deferred saturation signals

NATS JetStream queue depth and Postgres saturation (connection pool,
replication lag) are not monitored here. The exporters that would feed them
(prometheus-nats-exporter, postgres_exporter) are optional homelab-side
installs — a deliberate decision, not an oversight: cvgen's data plane is
small enough that the four golden signals above cover the failure modes
that page today. If installed, they belong to the fleet monitoring stack
and would flow through the same vmalert → Telegram pipe; revisit if queue
lag ever becomes an observable pain.

## Game day

A fault-injection game day — killing the S3 sidecar mid-download, poisoning
a NATS subject, throttling the gateway — is planned as roadmap item O2 and
will get its own doc when scheduled. Until then, the sections above are the
first-response path; do not tune thresholds based on intuition alone.

## Routing

Nothing in this repo configures notification delivery. The fleet-wide
Alertmanager runs a single catch-all Telegram receiver that already routes
every vmalert alert, including these (ADR 0015); the always-firing
`Watchdog` heartbeat and `severity: info` alerts are blackholed fleet-side,
so warnings and criticals land in Telegram and everything else stays
silent. `deploy/k8s/alerting` will be picked up by a fleet-side Flux
Kustomization entry after owner notification — no wiring exists or belongs
here.
