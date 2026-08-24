# 0008: VictoriaTraces rejected OTLP with 400s

**Symptom.** Traces missing; the collector's `otlphttp/victoriatraces`
exporter logged 400s.

**Root cause.** The exporter's `endpoint:` config appends
`/v1/traces` — but VictoriaTraces wants
`/insert/opentelemetry/v1/traces`. The doubled/wrong path 400'd.

**Fix.** Use `traces_endpoint:` (full-path override, no appending) →
`...:10428/insert/opentelemetry/v1/traces`.
