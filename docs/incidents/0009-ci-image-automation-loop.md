# 0009: CI ↔ image-automation infinite loop

**Symptom.** (Spotted live.) fluxcdbot bump commits kept triggering new
image builds, which minted new tags (`main-5` → `7` → `9` …), which
triggered new bumps — forever. Mitigated immediately with
`flux suspend image update cvgen`.

**Root cause.** The docker job ran on **every** main push, including the
bot's own manifest-bump commits. Each build got a fresh `run_number`-based
tag, the ImagePolicy saw a "newer" version, pushed another bump, and the
cycle closed.

**Fix.** Added an `images` path filter to the `changes` job and gated
docker + e2e on it — bot commits touch only `deploy/k8s`, so they no
longer build images. Resumed automation; exactly one converging bump.
The same invariant later scoped Renovate away from `deploy/k8s/**`.

**Lesson.** Any automation that commits to the branch that triggers
automation needs a cycle-breaker. Path filters are the cheapest one.

**Related non-bug:** two bump commits appearing at once is ImagePolicy
scan-timing convergence (the migrate image builds/scans first), not a
loop.
