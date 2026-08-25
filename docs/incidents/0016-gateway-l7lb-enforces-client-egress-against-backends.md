# 0016: The Gateway listener enforced each client's *egress* policy against the real backend — and we spent weeks blaming envoy routing

**Symptom.** Two surfaces, one shared signature:

1. Every Flagger canary of the gateway stalled at `Halt advancement no
   values found for custom metric: success-rate` ×5 → rollback. The canary
   pod was 1/1 Ready, served 200 on direct curl, had a Service endpoint,
   correct HTTPRoute weights — and an **empty access log**. Zero requests
   reached it. Manual traffic bursts from ad-hoc pods split 10/20 across
   primary/canary perfectly; the loadtester's steady stream reached
   nothing.
2. The synthetic CronJob failed every run: `GET / → 403`, body
   `Access denied`, `server: envoy`. Same body from a bare debug pod
   hitting the Gateway VIP.

Public traffic (world) worked throughout. Everything internal through
the Gateway VIP returned 403 or nothing at all.

**Investigation.** This ran across several sessions because every signal
lied (see "Why every prior conclusion was wrong" below).

1. Hubble compact output showed the request reaching
   `cilium-gateway-cvgen-gateway:80` with an `(ingress)` tag and
   `http-request DROPPED` — read as the Gateway's ingress authz denying.
2. JSON flow records flipped the attribution:
   `traffic_direction=EGRESS`, destination identity `reserved:world`,
   source re-labeled `reserved:ingress` (identity 8) at the listener.
3. cilium-envoy's admin socket (`/config_dump` over the unix admin.sock)
   showed no RBAC filter in the listener at all — but a
   `cilium.l7policy` HTTP filter plus `"enforce_policy_on_l7lb": true`
   in `cilium.bpf_metadata`.
4. Trace logging on the envoy (`POST /logging?filter=trace`) caught the
   decisive line during one denied request:
   ```
   CiliumPolicyFilterState(): source_identity: 8, ingress: false,
     port: 80, pod_ip: <client-pod-ip>, proxy_id: 14598 ...
   Pod policy DENY on proxy_id: 14598 id: 65447 port: 8080
   ```
   `65447` is the **gateway-primary pod's identity**, `8080` its real
   port. The listener was authorizing the original client against the
   selected backend.
5. A/B isolation: identical `GET /` to the VIP — unlabeled pod **200**,
   pod labeled `app=cvgen-synthetic` **403**. Difference: the labeled
   pod is selected by its own egress CNP; the unlabeled pod has none.
6. Direct pod→pod test (`curl gateway-primary-podIP:8080`) from a pod
   under a DNS-only egress CNP timed out with hubble showing
   `Policy denied DROPPED (TCP Flags: SYN)` on that pod's **egress**.

**Root cause.** Three stacked mistakes, all client-side:

1. **The l7lb enforcement point judges clients against real backends.**
   For any Gateway-API/L7 listener the cilium agent hardcodes
   `EnforcePolicyOnL7Lb = true`
   (`pkg/ciliumenvoyconfig/cec_resource_parser.go`; forced since 1.15,
   knob removed upstream). With it, the listener's `cilium.l7policy`
   filter evaluates the **original client's policies against the
   selected backend endpoint** — not against the VIP. So:
   - `cvgen-loadtester-egress` allowed `toEntities: [host]` port 80 —
     written for "the VIP is host-network". Kernel-level TCP to the VIP
     passed; then envoy checked loadtester→`gateway-primary:8080` and
     found nothing allowing it. **Every canary request was denied by the
     client's own egress rule.** Flagger saw zero traffic on primary
     *and* canary → "no values found" → rollback loop.
   - `cvgen-synthetic-egress` allowed DNS + world:443. Public DNS points
     `cv.corruptmane.xyz` straight at the Gateway VIP (no CDN), so the
     probe never left the cluster: TCP passed as "world", then envoy
     denied probe→backend:8080. 403.
2. **A namespace-wide DNS-only egress CNP** (`endpointSelector: {}`,
   port 53 only) silently put every cvgen pod *without* its own egress
   policy into enforcement. Debug pods and run-once jobs could do DNS
   and nothing else. It added nothing for real workloads (each already
   carries DNS in its own contract).
3. **The earlier conclusions this produced were wrong.** Incident
   [0011](0011-netpol-default-deny-behind-cilium-gateway.md) recorded
   "envoy RBAC enforces ingress regardless of audit mode" and shipped
   `fromEntities: [host]` on the gateway-ingress rule as the fix — both
   incorrect readings of the same mechanism. The CEC weight mismatch we
   chased ("envoy drift") was post-rollback residue; routing config was
   never wrong. Hubble's compact output actively misled: the drop is
   *observed at* the ingress listener but *attributed to* the client's
   EGRESS direction.

**Fix.**
- Removed the empty-selector DNS CNP entirely
  (`netpol: remove namespace-wide DNS-only egress policy`).
- Client egress contracts now name the actual backends they reach
  through the VIP: loadtester and synthetic both gained
  `toEndpoints app In [gateway, gateway-primary] :8080/TCP`;
  the loadtester's `host:80` entity rule went away
  (`netpol: allow loadtester+synthetic egress to gateway backends`).
- Gateway-ingress rule restored to plain allow-all-on-8080 (no `from`),
  dropping the 0011-era `fromEntities` rationale.
- Verified end-to-end: synthetic job PASS (full pipeline incl. PDF),
  then the first fully autonomous canary promotion —
  Progressing 10→50 on real loadtester metrics → Succeeded, zero manual
  bursts.

**Related non-bug.** The `CiliumEnvoyConfig` showing stale-looking
backend weights after a rollback looked like config drift but was just
Flagger's reset state; HTTPRoute `Accepted=True`/generation-match was
accurate all along.

**Lesson.**
1. Behind a Cilium Gateway, a client's egress contract must describe the
   path *all the way to the backend*, not up to the front door. Write
   client rules as `toEndpoints <service pods> :<backend port>`, not as
   entities aimed at the listener.
2. When internal-via-VIP fails while world-via-VIP works, diff the two
   clients' *policies*, not the listener's config. An unlabeled control
   pod is the cheapest discriminator there is.
3. Compact observability output lies by omission; before theorizing,
   escalate one level (JSON fields → envoy admin trace) and reproduce
   with deterministic timing (pre-created exec pods, not `kubectl run`).

See also [0017](0017-cnpg-control-plane-severed-froze-flux.md) for how
the same policy set froze GitOps itself, and the corrected mechanism
note in [0011](0011-netpol-default-deny-behind-cilium-gateway.md).
