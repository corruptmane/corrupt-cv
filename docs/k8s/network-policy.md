# Network policy (CiliumNetworkPolicy, enforced)

L4 segmentation for the `cvgen` namespace via `cilium.io/v2`
CiliumNetworkPolicies — thirteen documents in
`deploy/k8s/infra/cilium-policies.yaml`, no ClusterwidePolicies, no L7.
The model is **default-deny via explicit allows**: a pod is only ever
selected by policies that grant exactly its real flows; there is no
namespace-wide catch-all policy (both attempts at one backfired — see
[incident 0016](../incidents/0016-gateway-l7lb-enforces-client-egress-against-backends.md)).
CNP allows are additive across policies, so file order carries no
enforcement semantics.

The set is **enforced** (`policy-audit-mode` removed after a clean audit
cycle). Deep rationale for the non-obvious rules lives in incident
reports; this page stays declarative.

## Selector rationale

Every selector was chosen against what actually exists in the cluster:

| Workload | Pod selector | Why this label |
|---|---|---|
| gateway | `app In [gateway, gateway-primary]` | Authored as `app: gateway`, but Flagger relabels the promoted primary's pods to `app=gateway-primary`; every "serving gateway" selector lists BOTH values. |
| ai-processor | `app: ai-processor` | Authored in `deploy/k8s/apps/ai-processor.yaml`. |
| cv-generator | `app: cv-generator` | Authored in `deploy/k8s/apps/cv-generator.yaml`. |
| valkey | `app: valkey` | Authored in `deploy/k8s/infra/valkey.yaml`. |
| Postgres | `cnpg.io/cluster: cvgen-db` | Stamped by the CNPG operator on every instance pod; role labels have changed scheme before, so they are never selected on. |
| NATS | `app.kubernetes.io/name: nats` | Official Helm chart stamps these on every pod. |
| migrations Job | `batch.kubernetes.io/job-name: cvgen-migrate` | Kubernetes adds job-name to Job pods automatically. |
| synthetic probe | `app: cvgen-synthetic` | The single additive pod-template label on `apps/synthetic-cronjob.yaml`; per-run job-names are not stable selectors. |
| DNS target | ns `kube-system` + `k8s-app: kube-dns` | Standard CoreDNS labels; cross-namespace selectors carry the `k8s:` source prefix. |

## The Gateway rule that shapes client egress

Behind a Cilium Gateway listener, traffic from an in-cluster client is
authorized against the **selected backend** (gateway pods :8080), not
the VIP. Any client whose egress CNP aims at entities ("host:80",
"world:443") instead of the backend pods passes TCP and then gets an
envoy-generated `403 Access denied`. This broke every canary and the
synthetic probe until the client contracts named the gateway pods
explicitly. Full story:
[incident 0016](../incidents/0016-gateway-l7lb-enforces-client-egress-against-backends.md).

## Control-plane paths are part of the contract

CNPG instances talk to the API server (readiness probe) and accept
status extraction from the operator on :8000. Omitting either looks like
a healthy workload with degraded control — and the resulting unhealthy
Cluster resource froze the entire Flux dependsOn chain
([incident 0017](../incidents/0017-cnpg-control-plane-severed-froze-flux.md)).

## Policy inventory

| # | Policy | Selects | Grants |
|---|---|---|---|
| 1 | `cvgen-allow-gateway-ingress` | gateway pair | ← any source 8080/TCP |
| 2 | `cvgen-allow-ops-ingress` | three services + primary | ← monitoring ns 9090/TCP |
| 3 | `cvgen-gateway-egress` | gateway pair | → pg 5432, valkey 6379, nats 4222, OTLP 4318, DNS, world 443 |
| 4 | `cvgen-ai-processor-egress` | ai-processor | → nats 4222, valkey 6379, OTLP 4318, DNS, world 443 |
| 5 | `cvgen-cv-generator-egress` | cv-generator | → nats 4222, OTLP 4318, DNS, world 443 |
| 6 | `cvgen-migrations-egress` | migrate Job pods | → pg 5432, DNS |
| 7 | `cvgen-synthetic-egress` | synthetic pods | → gateway pods 8080 ([0016](../incidents/0016-gateway-l7lb-enforces-client-egress-against-backends.md)), world 443, DNS |
| 8 | `cvgen-cnpg-egress` | CNPG instance pods | → DNS, world 443 (WAL archive), kube-apiserver 443+6443 ([0017](../incidents/0017-cnpg-control-plane-severed-froze-flux.md)) |
| 9 | `cvgen-allow-valkey-ingress` | valkey | ← app services 6379/TCP |
| 10 | `cvgen-allow-nats-ingress` | nats | ← app services 4222/TCP |
| 11 | `cvgen-allow-postgres-ingress` | CNPG instance pods | ← gateway pair + migrate Job 5432/TCP; ← cnpg-system operator 8000/TCP ([0017](../incidents/0017-cnpg-control-plane-severed-froze-flux.md)) |
| 12 | `cvgen-allow-loadtester-ingress` | loadtester | ← flagger (flagger-system) 8080/TCP |
| 13 | `cvgen-loadtester-egress` | loadtester | → gateway pods 8080 ([0016](../incidents/0016-gateway-l7lb-enforces-client-egress-against-backends.md)), DNS |

Pods without a matching allow simply have no policy selecting that
direction — debug pods included, deliberately: ad-hoc tooling must work
without whack-a-mole label edits.

## Metrics ride OTLP push, not scrape

There is no `/metrics` endpoint on any cvgen pod; services push OTLP to
the fleet collector, so each service's egress explicitly allows TCP 4318
to the `monitoring` namespace (namespace-scoped, no podSelector, so a
collector chart label change degrades to "slightly too broad", never to
a dead rule). Flagger's canary gates read those series back from
VictoriaMetrics — a missing OTLP allow stalls canary analysis too. The
single ops rule allows tcp/9090 into the three services from `monitoring`
only.

## Deferred items

1. **FQDN-scoped HTTPS egress** — world:443 rules are port-scoped only;
   `toFQDNs` needs the fleet's DNS proxy enabled.
2. **serviceAccount selectors** — labels proved mendacious once already
   (Flagger relabel); migrating selectors onto dedicated SAs is the
   long-term tightening path.

## Verification

```sh
# Reconciliation picked the file up
flux get kustomizations --namespace flux-system | grep infra
kubectl get cnp -n cvgen          # expect the 13 documents above

# No unexpected drops between real workloads
just hubble-relay-fwd
hubble observe --namespace cvgen --verdict DROPPED --since 24h

# Front door answers
curl -sSI https://cv.corruptmane.xyz | head -n1   # expect HTTP/2 200 or 30x

# Backups advance
kubectl -n cvgen exec cvgen-db-1 -c postgres -- \
  psql -c 'select archived_count from pg_stat_archiver;'
```

Any unexpected DROPPED entry between two real identities = a missing
allow: fix `cilium-policies.yaml`, do NOT add a namespace-wide loosener
(see [0016](../incidents/0016-gateway-l7lb-enforces-client-egress-against-backends.md)).
