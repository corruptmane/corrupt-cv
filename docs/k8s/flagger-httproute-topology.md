# Flagger ↔ HTTPRoute ownership

At rest, `cv.corruptmane.xyz` is served through a short chain: the authored
Gateway `cvgen-gateway` (`deploy/k8s/apps/gateway-api.yaml`) terminates TLS on
its :443 listener at the `cvgen-tls` certificate, and a single Flagger-owned
HTTPRoute forwards all traffic to one backend — the `gateway-primary` Service
at full weight. During an analysis window only the route changes: Flagger
rewrites its backendRefs each minute, shifting weight from primary to canary
in 10-point steps up to 50% (`deploy/k8s/canary/canary.yaml`: `interval: 1m`,
`stepWeight: 10`, `maxWeight: 50`, rollback after `threshold: 5` failed
checks). The Gateway, certificate, and DNS record are static; the weights are
the moving part. The metric gates that decide the shift (success-rate ≥99%,
p99 ≤500ms) are covered in
[ADR 0012](../adr/0012-k8s-flux-flagger-topology.md) and not repeated here.

## What Flagger creates at reconcile time

From the `Canary` resource alone, Flagger mints everything the authored
manifests deliberately omit: the `gateway`, `gateway-primary`, and
`gateway-canary` Services derived from the Canary's `service` block (port 80 →
targetPort 8080), the weighted HTTPRoute bound to `cvgen-gateway` via the
Canary's `gatewayRefs`, and one more action — scaling the authored `gateway`
Deployment to zero once the primary clone is up
(`deploy/k8s/apps/gateway.yaml:2-4`; ADR 0012 lists this under Consequences,
including the corollary that debugging must target `gateway-primary-*` pods,
never the authored Deployment). The HTTPRoute is also the DNS source of truth:
external-dns watches it and manages the Cloudflare record for
`cv.corruptmane.xyz` from its hostnames — delete the route and the record's
anchor goes with it (`docs/k8s/homelab-integration.md`, verified cluster
facts).

## The deliberate absences

Neither `deploy/k8s/apps/gateway-api.yaml` nor `deploy/k8s/apps/gateway.yaml`
authors an HTTPRoute or a Service. The Gateway manifest's leading comment
states why: the HTTPRoute is deliberately absent because Flagger (provider
`gatewayapi:v1`) creates and owns it, moving weighted backendRefs between the
primary and canary Services during analysis, and external-dns picks the
hostname up from that Flagger-managed route. Hand-authoring either object
would create a second owner for something Flagger rewrites continuously.

One deviation is intentional: the Gateway keeps a plain-HTTP :80 listener
alongside :443, against the homelab's https-only norm. The reason is the
loadtester webhook (`deploy/k8s/canary/canary.yaml:42-50`), which drives
synthetic canary traffic *in-cluster* through the Gateway's own Service
(`cilium-gateway-cvgen-gateway.cvgen.svc`) so that weighted routing actually
applies — a homelab has no organic load during a ten-minute window. Inside the
cluster there is no way to make TLS for the public hostname verify, so the
synthetic leg rides plain HTTP while real user traffic still enters over
HTTPS.

## The apps↔canary revert race

The split between `apps` and `canary` Kustomizations has bitten once
([incident 0010e](../incidents/0010-alerting-saga.md#10e-the-revert-race-a-vacuous-canary-failure)). After a canary drill, the
revert push changed two objects — the Deployment (reconciled by `cvgen-apps`)
and the gate thresholds (reconciled by `cvgen-canary`) — which Flux applies on
independent schedules. The push produced two runs: the first promoted the
reverted spec cleanly; the second re-detected a revision (a stale re-apply of
the drill-era Deployment spec) and analyzed it against the still-unreverted
drill gate (`min: 101`), where success-rate 100 < 101 failed five checks and
rolled back to `Phase: Failed`. The failure was vacuous — Flagger's own
`lastAppliedSpec == lastPromotedSpec` showed the "failed" spec was identical
to what was already serving.

The fix became a permanent knob: the pod-template annotation
`cvgen.dev/rollout-nonce` (`deploy/k8s/apps/gateway.yaml:19-22`) — bumping it
in git forces a fresh canary run with zero functional change, which is how the
stale `Failed` status was cleared and how any future spec/policy coupling is
un-stuck. The lesson generalizes: in GitOps, two files in one commit ≠ one
atomic apply, so any workflow pairing a workload change with a policy change
must tolerate the window where only one has landed.

## Inspecting live topology

From a cluster context (fleet repo for the last command):

```sh
kubectl get httproute -A          # the Flagger-owned route in cvgen
kubectl get svc -n cvgen          # gateway, gateway-primary, gateway-canary
kubectl get canaries -n cvgen     # gateway: Phase Succeeded at rest
flux get kustomizations           # cvgen-apps and cvgen-canary both Ready
```

Healthy looks like this: one HTTPRoute parented to `cvgen-gateway` for host
`cv.corruptmane.xyz`, carrying a single backend (`gateway-primary`) when no
rollout is active; during analysis the same route shows two backends with
shifting weights that return to primary-only afterwards. Three Services exist
permanently even though only `gateway-primary` receives traffic at rest — the
authored Deployment behind `gateway` sits at zero replicas. If `kubectl get
canaries` shows `Failed` while the route already points fully at primary, you
are looking at a vacuous failure like §10e; check
`lastAppliedSpec == lastPromotedSpec` before treating it as an outage, and use
the nonce if a re-run is wanted.

## Failure modes if someone hand-creates an HTTPRoute

An HTTPRoute authored by hand for `cv.corruptmane.xyz` collides with Flagger's
on every axis. Two routes claiming the same hostname on the same Gateway means
duplicate or conflicting matches, with attach precedence — not intent —
deciding which one wins. During analysis Flagger rewrites weights on *its*
route every minute, so a hand-edited route's weights silently fight it and
traffic splits unpredictably across the two. external-dns then sees two
sources for one hostname and the Cloudflare record flaps between whatever each
route last advertised. None of this fails loudly; it degrades routing and DNS
quietly. The remedy is always the same: delete the hand-made route and let
Flagger recreate the one it owns — it will, on the next reconcile, with the
correct backends and the hostname external-dns expects.
