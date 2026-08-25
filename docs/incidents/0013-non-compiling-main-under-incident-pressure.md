# 0013: A non-compiling main pushed under incident pressure

**Symptom.** Minutes after landing the readiness-probe fix, CI's `go` job
failed on `origin/main`: `c.Put undefined (type *Client has no field or
method Delete)` — and with the gateway image unbuildable, the deploy
train stalled mid-flight while the other three services' images rolled
on without it.

**Investigation.** The commit had been made in the middle of a live
incident (see [0011](0011-netpol-default-deny-behind-cilium-gateway.md)
and [0012](0012-s3-existence-obfuscation-vs-readyz-probe.md)): production
degraded, several fixes deep, and the probe design had just changed
twice. Two compounding slips:
1. The verification block ran build *before* the final edit, as separate
   shell statements rather than a fail-fast chain — so a failed build did
   not stop the subsequent commit + push.
2. While the fix was being iterated, Flux's image-automation bot pushed
   tag-bump commits to `main` repeatedly. Every push was rejected
   non-fast-forward, every retry rebased onto new bot commits, and one
   soft-reset swept two unrelated bot-bump tag edits into the fix commit,
   which then conflicted with origin during rebase.

**Root cause.** Process: no fail-fast gate between "final edit" and
"push", applied during exactly the window when context-switching pressure
is highest.

**Fix.** `git reset --soft` back to the last good commit, stage only the
intended file, re-commit clean, resolve the single real conflict by
taking the fixed file wholesale against the broken upstream version,
verify `go build` on the **post-rebase tree**, then push. Landed green;
CI confirmed success including image builds from the renamed module.

**Lesson.**
1. Incident-time pushes need *stricter* gates, not looser ones: run
   `build && test && push` as one chained command so failure aborts the
   train, and never let commit/push execute after a failed verification.
2. Verify on the tree you actually ship — post-rebase, not pre-rebase.
3. When a bot owns part of your branch, expect it to move; loop
   `pull --rebase → push` until accepted instead of hand-fixing each race.
