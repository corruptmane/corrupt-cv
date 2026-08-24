# Network policy (W10)

L4 segmentation for the `cvgen` namespace, defined in
`deploy/k8s/infra/netpol.yaml` as vanilla `networking.k8s.io/v1`
NetworkPolicies — no CiliumNetworkPolicy resources. The model is
**default-deny, then explicit allows**: one policy selects every pod in
`cvgen` with empty `ingress: []` / `egress: []`, and nine allow policies
carve out exactly the flows the architecture needs (ADR 0012 topology:
gateway → NATS/Valkey/Postgres/S3-download; ai-processor →
NATS/Valkey/LLM APIs; cv-generator → NATS/S3-upload; migrations Job →
Postgres; synthetic probe → public HTTPS). Kubernetes NetworkPolicy is
additive, so file order carries no semantics — the deny is documented
first so the manifest reads top-down.

## Selector rationale

Every selector was chosen against what actually exists in the cluster,
not what would be convenient:

| Workload | Pod selector | Why this label |
|---|---|---|
| gateway | `app: gateway` | Authored in `deploy/k8s/apps/gateway.yaml`. Flagger's canary/primary clones preserve pod-template labels, so both sides match. |
| ai-processor | `app: ai-processor` | Authored in `deploy/k8s/apps/ai-processor.yaml`. |
| cv-generator | `app: cv-generator` | Authored in `deploy/k8s/apps/cv-generator.yaml`. |
| valkey | `app: valkey` | Authored in `deploy/k8s/infra/valkey.yaml`. |
| Postgres | `cnpg.io/cluster: cvgen-db` | Stamped by the CNPG operator on every instance pod of the Cluster named `cvgen-db` (`deploy/k8s/db/cluster.yaml`). This is the one label the operator guarantees across versions; role labels (`cnpg.io/instanceRole`, formerly `role`) have changed scheme before, so selecting on them would couple netpol to an operator version. Role-agnostic also means rw/ro/r service backends all match. |
| NATS | `app.kubernetes.io/name: nats` | The official `nats` Helm chart (HelmRelease in `infra/nats.yaml`) stamps its `selectorLabels` helper output on every pod; verified against the chart's `_helpers.tpl`. |
| migrations Job | `batch.kubernetes.io/job-name: cvgen-migrate` | `migrations/job.yaml` authors no pod-template labels; Kubernetes adds `batch.kubernetes.io/job-name` to every Job pod automatically, so the policy works without touching the Job. |
| synthetic probe | `app: cvgen-synthetic` | CronJob pods only get a **per-run** job-name (`cvgen-synthetic-<ts>`), which vanilla selectors cannot prefix-match. W10 added a single additive pod-template label (`app: cvgen-synthetic`) to `apps/synthetic-cronjob.yaml`; nothing else reads it. |
| DNS egress target | ns `kube-system` + `k8s-app: kube-dns` | Standard CoreDNS labels; namespace pinned via the immutable `kubernetes.io/metadata.name` label. |

## Two facts that shaped the rules

**Metrics ride OTLP push, not scrape.** cvgen services push OTLP to the
fleet collector (ADR 0010 / docs/k8s/alerting.md); there is no `/metrics`
endpoint on any cvgen pod, and the estate's only scrape is flagger itself
in `flagger-system`. A blanket vmagent→pods ingress rule would be dead
config, so there isn't one. The single ops rule allows tcp/9090 into
gateway/ai-processor/cv-generator from the `monitoring` namespace only —
it covers health/readyz inspection and any future VMPodScrape.

The push model cuts both ways: because telemetry is *egress*, each service
egress policy explicitly allows TCP 4318 to the `monitoring` namespace.
Under default-deny, omitting that stanza would silently drop every span,
metric and log record — and Flagger's canary gates read those series back
from VictoriaMetrics, so a missing allow stalls canary analysis too. The
allow is namespace+port scoped (no podSelector) so a collector chart label
change can never turn it into a dead rule.

**The internet-facing listener is host-network envoy.** Cilium Gateway
API listeners run on the host network, and vanilla NetworkPolicy source
selectors cannot select host-network pods as ingress sources. The
gateway's :8080 ingress allow therefore has **no `from` clause** —
allow-all-sources semantics, deliberately scoped to that one port so the
blast radius is exactly the public listener. Future tightening path: a
CiliumNetworkPolicy with `fromEntities: [host, world]`. Flagger's
loadtester→gateway traffic during canaries traverses the same host-envoy
path (the cilium-gateway Service), so it is covered by the same rule.

## Allow matrix

| Source | Destination | Port | Why |
|---|---|---|---|
| any (host-envoy, loadtester, internet) | gateway | 8080/TCP | Public HTTP entry; no `from` because host-network envoy is unselectable under vanilla NP. |
| monitoring namespace | gateway / ai-processor / cv-generator | 9090/TCP | Health/readyz inspection + future VMPodScrape; NOT metrics ingestion (OTLP push). |
| all cvgen pods | kube-system CoreDNS | 53 UDP+TCP | Name resolution for svc names and external endpoints. |
| gateway | Postgres (`cnpg.io/cluster: cvgen-db`) | 5432/TCP | Durable job history. |
| gateway | valkey | 6379/TCP | API-key provisioning + sessions (`SET EX 900`). |
| gateway | nats | 4222/TCP | Publishes requested/rendered, consumes all events. |
| gateway | any, 443/TCP | 443/TCP | S3 GetObject PDF downloads (verified in `services/gateway/internal/s3/s3.go`). Not FQDN-restricted — vanilla NP cannot express DNS destinations. |
| ai-processor | nats | 4222/TCP | Consumes requested, publishes structured. |
| ai-processor | valkey | 6379/TCP | GETDEL api-key handoff (exactly-once). |
| ai-processor | any, 443/TCP | 443/TCP | LLM provider APIs (user-supplied keys, provider set varies per request). CiliumNetworkPolicy FQDN rules = future option. |
| cv-generator | nats | 4222/TCP | Consumes structured, publishes rendered. |
| cv-generator | any, 443/TCP | 443/TCP | S3 PutObject of rendered PDFs. |
| migrations Job (`batch.kubernetes.io/job-name: cvgen-migrate`) | Postgres | 5432/TCP | goose SQL migrations. |
| synthetic probe (`app: cvgen-synthetic`) | any, 443/TCP | 443/TCP | Public blackbox probe of https://cv.corruptmane.xyz; re-enters through the :8080 rule above. |

Everything else in `cvgen` is denied in both directions by
`cvgen-default-deny-all`.

## Deferred items

Deliberately not done in W10, with the documented upgrade paths:

1. **FQDN-scoped HTTPS egress** — gateway→S3 and ai-processor→LLM APIs
   are port-scoped only. Vanilla NetworkPolicy has no DNS-name
   destinations; a CiliumNetworkPolicy with `toFQDNs` rules would narrow
   these when wanted.
2. **Host-envoy source tightening** — replace the open :8080 ingress
   allow with a CiliumNetworkPolicy using `fromEntities: [host, world]`.
3. **Live-cluster verification** — see below; intentionally deferred to
   deploy time (this workstream is declarative YAML + docs only).

## Verification after deploy

Executable steps for the owner once Flux reconciles the infra layer.
Nothing here runs at authoring time.

```sh
# 1. Confirm reconciliation picked the new file up (netpol.yaml is last
#    in deploy/k8s/infra/kustomization.yaml).
flux get kustomizations --namespace flux-system | grep infra
kubectl get networkpolicies -n cvgen

# 2. Default-deny proof: a bare pod in cvgen must fail BOTH directions.
kubectl run np-probe -n cvgen --rm -it --image=curlimages/curl:8.21.0 --restart=Never \
  -- curl -m 5 -sv https://example.com ; echo "expect timeout/fail"

# 3. DNS still resolves from inside cvgen (UDP+TCP 53 allow).
kubectl run np-dns -n cvgen --rm -it --image=busybox:1.36 --restart=Never \
  -- nslookup nats.cvgen.svc.svc.cluster.local

# 4. In-cluster data plane still talks: gateway → nats/valkey/postgres.
#    Simplest signal: submit a fake-model job end-to-end.
open https://cv.corruptmane.xyz   # pick Fake (canned CV), watch it complete

# 5. Host-envoy path proof: public front door answers (covered by the
#    port-scoped no-from rule).
curl -sSI https://cv.corruptmane.xyz | head -n1   # expect HTTP/2 200 or 30x

# 6. Synthetic probe survives its next scheduled run (its 443 egress +
#    re-entry through :8080).
kubectl get jobs -n cvgen -w   # next top-of-hour: cvgen-synthetic-<ts> Complete

# 7. Hubble: watch for unexpected DROPS for ~5 minutes under normal use;
#    anything dropped reveals a missing allow (add it to netpol.yaml, do
#    NOT loosen the default deny).
hubble observe --namespace cvgen --verdict DROPPED --since 5m
```

If step 7 shows drops from the kubelet probe ports or node CIDRs, note
that kubelet health/readiness probes are node-originated and unaffected
by ingress rules; investigate only drops between real pod IPs.
