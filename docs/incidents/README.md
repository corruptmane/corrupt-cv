# Incident log

Every real problem hit while building and operating cvgen — how each was
investigated, the root cause, and the fix. The [ADRs](../adr/) record the
*decisions*; these files record the *pain*. Public by design: if a lesson
was expensive enough to learn, it is cheap to share.

## Format

One file per incident, numbered `NNNN` in rough chronological order,
named `NNNN-kebab-case-title.md`. Sections use bold labels, in this order
(omit what adds nothing):

- **Symptom** — what was observed, verbatim where possible.
- **Investigation** — how the symptom was traced to the cause.
- **Root cause** — the actual mechanism, not the proximate one.
- **Fix** — what changed, with file/PR references.
- **Related non-bug** — lookalike behavior that turned out benign.
- **Lesson** — the transferable takeaway.

## Index

| File | Incident |
|---|---|
| [0001](0001-jetstream-backoff-overrides-ackwait.md) | JetStream redelivered messages mid-LLM-call (`BackOff` replaces `AckWait`) |
| [0002](0002-nats-kv-key-charset.md) | NATS KV rejected the model-catalog keys |
| [0003](0003-opendal-string-typed-options.md) | OpenDAL panicked on boolean options |
| [0004](0004-golangci-lint-version-drift.md) | CI golangci-lint failures (twice) |
| [0005](0005-k8s-validate-runner-image.md) | CI k8s-validate job fought the runner image |
| [0006](0006-flux-image-automation-crds.md) | Flux image automation: CRDs missing |
| [0007](0007-canary-metric-label-mapping.md) | Canary gates returned "no values found" (label-mapping mismatch) |
| [0008](0008-victoriatraces-otlp-endpoint-path.md) | VictoriaTraces rejected OTLP with 400s |
| [0009](0009-ci-image-automation-loop.md) | CI ↔ image-automation infinite loop |
| [0010](0010-alerting-saga.md) | The alerting saga (five distinct failures in one feature) |
| [0011](0011-netpol-default-deny-behind-cilium-gateway.md) | Default-deny NetworkPolicies behind a Cilium Gateway listener (deploy rollback) |
| [0012](0012-s3-existence-obfuscation-vs-readyz-probe.md) | S3 existence obfuscation vs the deep readiness probe |

## Meta-observations

- **The best validator was the cluster itself.** Server-side dry-runs
  caught the AlertProvider enum; live CRD inspection killed the
  Canary-eventSource idea; live PromQL caught the label mapping;
  `helm template` verified naming. Docs and priors were wrong or stale in
  every one of those cases.
- **Alerting was configured dark — and immediately proved itself.** The
  first real Telegram messages were the pipeline reporting *its own*
  bring-up problems, then resolving them. Ugly, but exactly the
  visibility that was missing.
- **Every "platform" bug was an integration seam**, not a component bug:
  client-vs-server config semantics (BackOff), chart-vs-cluster CRDs
  (podMonitor), scraper-vs-app label ownership (honor_labels),
  CI-vs-automation feedback (image loop), apply-ordering-vs-analysis-
  timing (revert race), client-vs-server policy direction (NetworkPolicy),
  policy-enforcement-point-vs-listener (envoy shadowing), IAM-vs-API
  error masking (S3 probes). Platform engineering is mostly seam
  engineering.
- **Unexplained, parked:** the homelab vmsingle stores one counter as
  `cvgen_jobs_seconds_total` (bogus `seconds` suffix from the
  Prometheus-naming translation). Non-blocking; worth a look someday.
