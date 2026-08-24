# 0007: Canary gates returned "no values found" (label-mapping mismatch)

**Symptom.** First canary analysis: `Halt advancement no values found for
custom metric: success-rate`.

**Investigation.** Ran the MetricTemplate PromQL by hand against the
cluster's vmsingle. The metric existed — but the label filters (`job`,
`instance`) matched nothing. Inspected actual series labels.

**Root cause.** The compose VictoriaMetrics mapped OTLP resource
attributes to `job`/`instance`; the homelab vmsingle surfaces them as
**`service_name`/`service_instance_id`**. Same product, different ingest
path, different label names.

**Fix.** Rewrote both MetricTemplates to use `service_name="gateway"` and
the `service_instance_id` pair — after validating the corrected queries
live (100% success rate, p99 5ms) *before* committing. Discrimination
between primary and canary pods rides
`OTEL_RESOURCE_ATTRIBUTES=service.instance.id=$(POD_NAME)`.

**Lesson.** Metric-gated deploys deserve a pre-flight: run the exact gate
query against the exact datastore before trusting it with rollbacks.
