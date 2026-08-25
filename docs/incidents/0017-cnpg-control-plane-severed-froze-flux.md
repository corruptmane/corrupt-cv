# 0017: Two missing CNP allows severed the database's control plane — and froze Flux fleet-wide

**Symptom.** A scheduled canary never started. Flagger's log was silent
for hours; the Canary CR sat in `Failed` from a pre-dawn run. The
database pod looked perfectly healthy (1/1 Running, serving queries,
WAL archiving advancing) but logged every 10 seconds:

```
readiness probe using cached cluster definition due to API server
connectivity issue   apiServerErr: Get https://10.96.0.1:443/...
clusters/cvgen-db: context deadline exceeded
```

And the Flux kustomization chain read `cvgen-db=Unknown`,
`cvgen-migrations/apps/canary/alerts=False`.

**Investigation.**
1. Hubble showed both directions of the control plane being dropped:
   `cvgen/cvgen-db-1 → kube-apiserver:6443 Policy denied DROPPED`
   repeatedly, and earlier `cnpg-system/operator → cvgen-db-1:8000
   Policy denied DROPPED`.
2. The db pod's own logs named the first one explicitly (above): CNPG's
   instance readiness probe GETs the Cluster resource from the API
   server and **falls back to a cached definition on failure** — which
   is why the pod stayed 1/1 and nobody noticed.
3. `kubectl get cluster cvgen-db` showed
   `Instance Status Extraction Error: HTTP communication issue`: the
   operator could not reach instance port 8000 (status endpoint).
4. The kustomization chain explained the frozen deploys:
   `cvgen-db`'s health check includes the Cluster resource; with status
   extraction broken it hung in Unknown, and every dependent
   (`cvgen-migrations → cvgen-apps → cvgen-canary → cvgen-alerts`)
   refused to reconcile. A pushed rollout-nonce bump therefore never
   reached the cluster — no new canary could start.

**Root cause.** The zero-trust CNP set modeled the database as an app
dependency (5432 server) and a backup client (S3 over world:443) but
not as a **control-plane participant**:

1. `cvgen-cnpg-egress` had no allow for the Kubernetes API server —
   every instance-side apiserver call timed out.
2. `cvgen-allow-postgres-ingress` allowed only app clients on 5432;
   the operator's status-extraction calls to instance port 8000 were
   denied.

The networking gap itself was minor; the *blast radius* came from Flux
health-gating: one unhealthy resource at the bottom of a dependency
chain suspends reconciliation for everything above it.

**Fix.** (`netpol: restore CNPG control-plane paths blocked by zero-trust policies`)
- `cvgen-cnpg-egress`: added `toEntities: [kube-apiserver]` 443/6443.
- `cvgen-allow-postgres-ingress`: added the `cloudnative-pg` operator
  (namespace `cnpg-system`) to instance port 8000/TCP.

Verified: connectivity-issue log lines stopped immediately, cluster
phase back to healthy, all five kustomizations Ready within one
reconcile cycle, pending manifest changes finally applied, canary
started and promoted ([0016](0016-gateway-l7lb-enforces-client-egress-against-backends.md)).

**Lesson.**
1. Infrastructure pods are clients of the *control plane*, not just of
   app dependencies. When writing egress policy for anything
   operator-managed (CNPG, cert-manager, …), enumerate its control-plane
   calls — apiserver, operator↔instance ports — as first-class entries.
2. Cached/fallback paths in probes are a silence machine: "degraded but
   Ready" hides outages by design. Alert on the degradation log line,
   not just pod phase.
3. Flux health checks turn any single stuck resource into a fleet-wide
   deploy freeze. When "nothing reconciles anymore", walk the dependsOn
   chain bottom-up and check the resource health each Kustomization
   gates on.

See [0016](0016-gateway-l7lb-enforces-client-egress-against-backends.md)
for the same policy set's other blind spot that day.
