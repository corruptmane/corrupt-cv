# Homelab integration

How `deploy/k8s/` reaches the cluster: the homelab fleet repo
(`corruptmane/homelab`) references this repo via a Flux `GitRepository` and
six `Kustomization`s (dependsOn chain `infra → db → migrations → apps →
canary`, plus `image-automation`). The fleet-side files live in the homelab
repo under `apps/cvgen/`.

## One-time pre-flight

1. **GHCR visibility**: make the four `cvgen-*` packages public (Settings →
   Packages), or add a pull secret + `secretRef` on each `ImageRepository`.
2. **Deploy key**: generate an SSH key, add it to `corruptmane/corrupt-cv` as a
   deploy key **with write access** (image automation pushes tag bumps),
   and create the Flux secret:
   ```sh
   flux create secret git cvgen-deploy-key \
     --url=ssh://git@github.com/corruptmane/corrupt-cv --private-key-file=<key>
   ```
3. **OpenTofu**: `infra/opentofu/` applied (bucket + IAM + the six
   `/homelab/cvgen-*` SSM parameters that the `cvgen-aws` ExternalSecret
   consumes).
4. **Monitoring**: the fleet PR extends the central otel-collector with
   metrics and logs pipelines and enables Prometheus naming on vmsingle
   (`-opentelemetry.usePrometheusNaming`) — required by the canary
   MetricTemplates and the metric names in ADR 0010.

## Verified cluster facts (2026-07-23)

- GatewayClass `cilium` (Accepted), Gateway API CRDs bundle v1.4.1
- ClusterSecretStore `aws-ssm` Ready
- `vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428`
- `otel-collector-opentelemetry-collector.monitoring.svc:4318`
- `victoria-logs-victoria-logs-single-server.monitoring.svc:9428`
- external-dns watches `gateway-httproute` → the Cloudflare record for
  `cv.corruptmane.xyz` is created from the Flagger-managed HTTPRoute
- cert-manager ClusterIssuer `letsencrypt-production` (Cloudflare DNS01)

## What Flagger owns

The `gateway` Deployment in `deploy/k8s/apps` has **no Service and no
HTTPRoute** on purpose: Flagger creates `gateway` / `gateway-primary` /
`gateway-canary` Services and the weighted HTTPRoute, and scales the
authored Deployment to zero after priming. Rollouts: images bumped by Flux
image automation → Flagger shifts 10%-step traffic through the Cilium
Gateway, gated on success-rate ≥99% and p99 ≤500ms measured from otelgin's
`http.server.request.duration` (canary pods isolated via the
`service_instance_id` label carrying the pod name — the cluster vmsingle
surfaces OTLP resource attributes as `service_name`/`service_instance_id`,
not `job`/`instance`).
