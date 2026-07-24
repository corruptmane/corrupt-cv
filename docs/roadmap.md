# Roadmap

v1 is deliberately compose-only (see [ADR 0011](adr/0011-anonymous-sessions-byo-key-v1.md)). The platform track below is sequenced roughly in order of intent.

## Platform

- ~~**Kubernetes manifests**~~ — **delivered** ([ADR 0012](adr/0012-k8s-flux-flagger-topology.md)): `deploy/k8s/` Kustomizations reconciled by the homelab fleet repo; compose stays the dev loop.
- ~~**Flux GitOps + Flagger canary**~~ — **delivered** ([ADR 0012](adr/0012-k8s-flux-flagger-topology.md)): Flagger `gatewayapi:v1` canaries on Cilium Gateway API, gated on VictoriaMetrics success-rate/p99, images rolled by Flux image automation.
- ~~**OpenTofu object storage**~~ — **delivered** ([ADR 0013](adr/0013-opentofu-s3-ssm-eso.md)) as AWS S3 + SSM/ESO secret chain; the original Hetzner-k3s idea was superseded by hosting on the existing homelab Talos cluster, leaving S3 as the only external infrastructure.
- ~~**Deployment alerting**~~ — **delivered** ([ADR 0015](adr/0015-deployment-alerting.md)): canary rollbacks (`flagger_canary_status` VMRule) and Flux reconciliation failures notify Telegram through a single ESO-configured Alertmanager; failures only.

## Product & scale

- **Multi-replica SSE fan-out** — per-connection ephemeral JetStream consumers (ADR 0005) are single-replica-friendly; scaling the gateway horizontally needs a fan-out layer so any replica can serve any job's event feed.
- **Paid plans / billing + real auth** — accounts (OAuth/email), operator-managed provider keys with quotas, metered usage; replaces the BYO-key-only model for paying users.

## Hardening

- **protovalidate** — schema-level constraints on the proto contracts, enforced at ingress and in CI, instead of hand-written validation.
- **DLQ revisit** — v1 rejected a dead-letter stream (ADR 0005) in favor of MAX_DELIVERIES advisories; revisit once there's a real need to inspect and replay poisoned events manually.
