# Network policy (W10 re-land, CiliumNetworkPolicy)

> **Status: STAGE 1 — AUDIT MODE.** The zero-trust set is authored as
> CiliumNetworkPolicies in `deploy/k8s/infra/cilium-policies.yaml` and
> lands while the cluster runs `policy-audit-mode=true` (fleet-side):
> policies load and LOG would-be drops without enforcing. This staging
> exists because v1 of this workstream shipped vanilla NetworkPolicies and
> was reverted within the hour (see
> [incident 0011](../incidents/0011-netpol-default-deny-behind-cilium-gateway.md)):
> default-deny is bidirectional, and behind a Cilium Gateway API listener
> its deny-all entry shadows narrower allows at envoy's RBAC enforcement
> point. Stage 2 (remove the audit flag) happens only after a clean
> `hubble observe --verdict AUDIT` cycle; this banner stays until then.

L4 segmentation for the `cvgen` namespace via `cilium.io/v2`
CiliumNetworkPolicies — fifteen documents in
`deploy/k8s/infra/cilium-policies.yaml`, no ClusterwidePolicies, no L7.
The model is **default-deny, then explicit allows**: one policy selects
every pod in `cvgen` with empty `ingress: []` / `egress: []`, and fourteen
allow policies carve out exactly the flows the architecture needs. CNP
allows are additive across policies, so file order carries no enforcement
semantics — the manifest reads top-down anyway: deny first, shared DNS,
ingress allows, per-workload egress, server-side ingress allows.

## What changed from the vanilla-NP attempt

| Problem in incident 0011 | CNP answer in this set |
|---|---|
| No server-side ingress allows for valkey/NATS/Postgres | Every client egress rule has an ingress twin (`cvgen-allow-{valkey,nats,postgres}-ingress`) |
| CNPG pod inside default-deny egress with no allow → WAL archiving froze silently | `cvgen-cnpg-egress`: DNS + world HTTPS for barman WAL/backup archive |
| Listener-path traffic judged by envoy RBAC where deny-all shadows allows | Gateway :8080 ingress uses `fromEntities: [host]` — the envoy terminating the Gateway API listener is host-network |
| Migration Job hung on a silent TCP connect | Migrations have BOTH halves now (`cvgen-migrations-egress` + postgres ingress) |

## Selector rationale

Every selector was chosen against what actually exists in the cluster,
not what would be convenient:

| Workload | Pod selector | Why this label |
|---|---|---|
| gateway | `app In [gateway, gateway-primary]` | Authored as `app: gateway` in `deploy/k8s/apps/gateway.yaml`, but Flagger relabels the promoted primary's pods to `app=gateway-primary`. Selecting only `app: gateway` would strand the replica actually serving production — every "serving gateway" selector lists BOTH values. |
| ai-processor | `app: ai-processor` | Authored in `deploy/k8s/apps/ai-processor.yaml`. |
| cv-generator | `app: cv-generator` | Authored in `deploy/k8s/apps/cv-generator.yaml`. |
| valkey | `app: valkey` | Authored in `deploy/k8s/infra/valkey.yaml`. |
| Postgres | `cnpg.io/cluster: cvgen-db` | Stamped by the CNPG operator on every instance pod of the Cluster named `cvgen-db` (`deploy/k8s/db/cluster.yaml`). The one label the operator guarantees across versions; role labels (`cnpg.io/instanceRole`) have changed scheme before. Role-agnostic also means rw/ro/r service backends all match. |
| NATS | `app.kubernetes.io/name: nats` | Official `nats` Helm chart (HelmRelease in `infra/nats.yaml`) stamps its `selectorLabels` helper output on every pod; verified against the chart's `_helpers.tpl`. |
| migrations Job | `batch.kubernetes.io/job-name: cvgen-migrate` | `migrations/job.yaml` authors no pod-template labels; Kubernetes adds `batch.kubernetes.io/job-name` to every Job pod automatically. |
| synthetic probe | `app: cvgen-synthetic` | CronJob pods only get a per-run job-name (`cvgen-synthetic-<ts>`); the single additive pod-template label on `apps/synthetic-cronjob.yaml` is the only stable selector. |
| DNS target | ns `kube-system` + `k8s-app: kube-dns` | Standard CoreDNS labels; cross-namespace selectors carry the `k8s:` source prefix Cilium puts on Kubernetes-derived labels, namespace pinned via `io.kubernetes.pod.namespace`. |
| loadtester | `app.kubernetes.io/name: loadtester` | Chart label from `deploy/k8s/infra/flagger-loadtester.yaml`. |

## Two facts that shaped the rules

**Metrics ride OTLP push, not scrape.** cvgen services push OTLP to the
fleet collector (ADR 0010 / docs/k8s/alerting.md); there is no `/metrics`
endpoint on any cvgen pod, and the estate's only scrape is flagger itself
in `flagger-system`. A blanket vmagent→pods ingress rule would be dead
config, so there isn't one. The single ops rule allows tcp/9090 into
gateway/ai-processor/cv-generator from the `monitoring` namespace only.

The push model cuts both ways: because telemetry is *egress*, each
service's egress policy explicitly allows TCP 4318 to the `monitoring`
namespace. Under default-deny, omitting that stanza would silently drop
every span, metric and log record — and Flagger's canary gates read those
series back from VictoriaMetrics, so a missing allow stalls canary
analysis too. The allow is namespace+port scoped (no podSelector) so a
collector chart label change degrades to "slightly too broad", never to a
dead rule.

**The internet-facing listener is host-network envoy.** Cilium Gateway
API listeners run on the host network, so requests reach gateway pods
from the `host` entity — this time expressible: `fromEntities: [host]`
on the :8080 ingress allow (vanilla NP could not name that source, which
is half of why incident 0011 happened). Flagger's loadtester rides the
same cilium-gateway VIP during canaries, so its traffic enters through
the same rule; conversely the loadtester's own *egress* targets the VIP,
hence `toEntities: [host]` on port 80 in `cvgen-loadtester-egress`.

## Policy inventory

| # | Policy | Selects | Grants |
|---|---|---|---|
| 1 | `cvgen-default-deny` | all cvgen pods | nothing — denies both directions |
| 2 | `cvgen-allow-dns-egress` | all cvgen pods | → kube-dns 53 UDP+TCP |
| 3 | `cvgen-allow-gateway-ingress` | gateway pair | ← host entity 8080/TCP |
| 4 | `cvgen-allow-ops-ingress` | three services + primary | ← monitoring ns 9090/TCP |
| 5 | `cvgen-gateway-egress` | gateway pair | → pg 5432, valkey 6379, nats 4222, OTLP 4318, DNS, world 443 |
| 6 | `cvgen-ai-processor-egress` | ai-processor | → nats 4222, valkey 6379, OTLP 4318, DNS, world 443 |
| 7 | `cvgen-cv-generator-egress` | cv-generator | → nats 4222, OTLP 4318, DNS, world 443 |
| 8 | `cvgen-migrations-egress` | migrate Job pods | → pg 5432, DNS |
| 9 | `cvgen-synthetic-egress` | synthetic pods | → DNS, world 443 |
| 10 | `cvgen-cnpg-egress` | CNPG instance pods | → DNS, world 443 (WAL archive!) |
| 11 | `cvgen-allow-valkey-ingress` | valkey | ← app services 6379/TCP |
| 12 | `cvgen-allow-nats-ingress` | nats | ← app services 4222/TCP |
| 13 | `cvgen-allow-postgres-ingress` | CNPG instance pods | ← gateway pair + migrate Job 5432/TCP |
| 14 | `cvgen-allow-loadtester-ingress` | loadtester | ← flagger (flagger-system) 8080/TCP |
| 15 | `cvgen-loadtester-egress` | loadtester | → host entity 80/TCP, DNS |

Everything else in `cvgen` is denied in both directions by policy 1.

## Deferred items

Deliberately not done, with documented upgrade paths:

1. **FQDN-scoped HTTPS egress** — world:443 rules are port-scoped only.
   CNP `toFQDNs` rules need the fleet's DNS proxy enabled; parked as
   Stage 3 in `.omo/plans/cilium-networkpolicy-zero-trust.md`.
2. **Enforcement** — Stage 2 removes the fleet-side
   `policy-audit-mode=true`; this banner comes off then.
3. **serviceAccount selectors** — labels proved mendacious once already
   (Flagger relabel); migrating selectors onto dedicated SAs is the
   long-term tightening path.

## Verification (Stage 1 — audit mode)

Executable steps for the owner once Flux reconciles the infra layer.

```sh
# 1. Confirm reconciliation picked the new file up (cilium-policies.yaml
#    is last in deploy/k8s/infra/kustomization.yaml).
flux get kustomizations --namespace flux-system | grep infra
kubectl get cnp -n cvgen

# 2. Audit evidence: after a full cycle (backup window 03:30 UTC, one
#    forced canary via cvgen.dev/rollout-nonce bump, one hourly synthetic,
#    one manual fake-model e2e), ONLY intended-matrix flows may appear.
just hubble-relay-fwd
hubble observe --namespace cvgen --verdict AUDIT --since 24h

# 3. Default-deny proof (still valid under audit mode — audit logs the
#    would-be drop): a bare pod in cvgen must fail BOTH directions.
kubectl run np-probe -n cvgen --rm -it --image=curlimages/curl:8.21.0 \
  --restart=Never -- curl -m 5 -sv https://example.com ; echo "expect timeout/fail"

# 4. Public front door answers throughout (host-entity ingress rule).
curl -sSI https://cv.corruptmane.xyz | head -n1   # expect HTTP/2 200 or 30x

# 5. Backups advance: WAL archiving survived its own egress rule.
kubectl -n cvgen exec cvgen-db-1 -c postgres -- \
  psql -c 'select archived_count from pg_stat_archiver;'
```

Any unexpected AUDIT entry = a missing allow: fix `cilium-policies.yaml`,
do NOT loosen the default deny, restart the cycle. Only when the cycle is
clean does Stage 2 remove the audit flag — then repeat step 2 with
`--verdict DROPPED` and expect zero entries between real pod IPs.
