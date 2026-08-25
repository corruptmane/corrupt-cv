# 0014: Hubble CLI rejected by the cluster's own relay ("invalid fieldmask")

**Symptom.** Recurring frustration: every check said Hubble was healthy —
`hubble-relay` and `hubble-ui` pods Running, services present, status
output green — yet the CLI could never observe flows, failing with:

```
Error "invalid fieldmask" on 2 nodes: homelab/<node-a>, homelab/<node-b>
```

Separately, port-forwards sometimes failed with `bind: address already in
use`, or bound successfully but reset every connection (`connection reset
by peer`) — stale tunnels from earlier sessions pointing at since-rotated
pods.

**Root cause.** Two unrelated issues sharing one symptom surface:
1. **CLI/relay version skew.** The locally installed hubble CLI (1.19.x)
   requests proto fieldmasks that the cluster's relay — pinned to the
   Cilium minor, 1.18.5 — does not serve. The gRPC call reaches the relay,
   which forwards it to nodes whose agents reject the unknown mask.
2. **Orphaned port-forwards.** Background `kubectl port-forward` processes
   outlive the shell work that started them: one holds the local port so
   new forwards can't bind; another keeps a dead tunnel whose target pod
   no longer exists, resetting every connection.

**Fix.**
1. Pin the CLI to the cluster's Cilium minor:
   `hubble v1.18.5` binary at a known path; flows then stream normally.
2. An explicit `just hubble-stop` recipe pkills stale forwards before
   re-forwarding.

**Lesson.** "Enabled" and "reachable" are different claims: match the
client's minor version to the server's, and treat long-lived
port-forwards as stateful resources that need an explicit stop path —
a dead tunnel looks exactly like a broken service from the client side.
