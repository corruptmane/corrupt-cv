# Roadmap

v1 is deliberately compose-only (see [ADR 0011](adr/0011-anonymous-sessions-byo-key-v1.md)). The platform track below is sequenced roughly in order of intent.

## Platform

- **Kubernetes manifests** — first-class manifests (Kustomize base + overlays) for all services, replacing compose as the deployment target while compose stays the dev loop.
- **Flux GitOps + Flagger canary** — cluster state reconciled from this repo via Flux; progressive delivery with Flagger canaries driven by metrics-based analysis against VictoriaMetrics (error rate, p99 latency) instead of manual promotion.
- **OpenTofu on Hetzner k3s** — infrastructure as code provisioning a k3s cluster on Hetzner Cloud: nodes, networks, load balancer, DNS, object storage.

## Product & scale

- **Multi-replica SSE fan-out** — per-connection ephemeral JetStream consumers (ADR 0005) are single-replica-friendly; scaling the gateway horizontally needs a fan-out layer so any replica can serve any job's event feed.
- **Paid plans / billing + real auth** — accounts (OAuth/email), operator-managed provider keys with quotas, metered usage; replaces the BYO-key-only model for paying users.

## Hardening

- **protovalidate** — schema-level constraints on the proto contracts, enforced at ingress and in CI, instead of hand-written validation.
- **DLQ revisit** — v1 rejected a dead-letter stream (ADR 0005) in favor of MAX_DELIVERIES advisories; revisit once there's a real need to inspect and replay poisoned events manually.
