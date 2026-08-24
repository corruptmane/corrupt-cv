# 0010: The alerting saga (five distinct failures in one feature)

Goal: "nothing notifies when a deployment fails." Telegram, failures
only. What followed was a chain of five independent gotchas.

## 10a. Flagger has no Telegram AlertProvider

**Investigation.** First design used Flagger's `AlertProvider` with
`type: telegram`. A **server-side dry-run**
(`kubectl apply --dry-run=server`) rejected it instantly: supported
values are slack/msteams/discord/rocket/gchat. Docs confirmed; no
generic event webhook in the alerting API either.

**Fix (redesign).** Flagger's docs point to the canonical escape hatch:
alert on the `flagger_canary_status` metric via Alertmanager. This
converged on a *better* architecture — the homelab's vmalert was firing
into `notifier.blackhole: true`, so enabling the VM-stack Alertmanager
with a Telegram receiver fixed cvgen alerting *and* un-blackholed every
built-in cluster rule. Flux failures ride the same pipe via
notification-controller's `alertmanager` provider (its Alert CRD can't
watch `Canary` objects — checked the live CRD enum — and its native
Telegram provider would have needed the chat id in a public repo;
Alertmanager keeps token *and* chat id in SSM via an ESO-templated
`alertmanager.yaml`).

**Lesson.** `--dry-run=server` against live CRDs beats docs and memory.
And when a tool lacks your channel, one shared pipe beats per-tool
adapters.

## 10b. flagger chart `podMonitor` requires prometheus-operator CRDs

**Symptom.** After pushing: `cvgen-infra` health check timeout; flagger
HelmRelease `UpgradeFailed: no matches for kind "PodMonitor" in version
"monitoring.coreos.com/v1"`.

**Root cause.** Assumed the VM operator's converter would translate the
chart's PodMonitor. Wrong: the converter only works if the PodMonitor
**CRD exists** — the object must be creatable first. This cluster runs
the VM stack without prometheus-operator CRDs.

**Fix.** Dropped the chart value; authored a native **`VMPodScrape`**
selecting `app.kubernetes.io/name: flagger` on port `http`. (The failed
upgrade never touched the running flagger pod — helm died at rendering —
so canaries were never at risk.)

## 10c. Alertmanager pods could never be created (63-char label limit)

**Symptom.** VMAlertmanager `failed`, StatefulSet 0/1, events:
`Create Pod ... failed: metadata.labels: Invalid value:
"vmalertmanager-victoria-metrics-victoria-metrics-k8s-stack-<hash>":
must be no more than 63 bytes`.

**Root cause.** The chart's doubled fullname plus the `vmalertmanager-`
prefix plus the StatefulSet's `controller-revision-hash` suffix exceeds
Kubernetes' 63-character **label value** limit — the StatefulSet
controller rejects every pod it tries to create.

**Investigation → fix.** Read the chart's naming helper
(`vm.managed.fullname` honors a per-component `name` override), then
**verified with `helm template`** against the exact chart version before
committing: `alertmanager.name: alertmanager` → CR `alertmanager`, pods
`vmalertmanager-alertmanager-0`, and the chart re-wires vmalert's
notifier automatically.

**Lesson.** Long helm release names are a time bomb with StatefulSets.
And `helm template | grep` is the fastest way to verify naming behavior
claims.

## 10d. The VMRule that could never fire (label collision)

**Symptom.** None — that's the problem. Found while verifying the
pipeline end-to-end: `flagger_canary_status` carried
`namespace="flagger-system"`, not `cvgen`.

**Root cause.** vmagent's default `honor_labels: false` renames the
*application's* `namespace` label (the canary's namespace, set by
flagger) to `exported_namespace`, and stamps the scrape target's
namespace instead. The rule's `{namespace="cvgen"}` filter matched zero
series — an alert that silently can never fire.

**Fix.** `honorLabels: true` on the VMPodScrape endpoint — flagger's own
labels (the canary's identity) win.

**Lesson.** An alerting rule isn't done when it's syntactically valid
and loaded — query the exact expression against live data and confirm it
*matches something* (or fire it once, deliberately).

## 10e. The revert race: a vacuous canary failure

**Symptom.** The post-drill revert should have promoted cleanly.
Instead: Canary `Failed`, weight 0.

**Investigation.** Flagger logs told the full story: the revert push
produced **two** runs. First run: gates passing, weights 30→50,
"Promotion completed" — production correctly on the reverted spec. Then,
minutes later: "New revision detected" *again* — a stale re-apply of the
drill-era Deployment spec — analyzed against the **still-unreverted
drill gate `min: 101`** (`Halt ... success-rate 100.00 < 101`), five
failed checks, rollback, `Phase: Failed`. The tell that it was vacuous:
`lastAppliedSpec == lastPromotedSpec` — the "failed" spec was
byte-identical to what was already promoted and serving.

**Root cause.** The revert changed two objects applied by *different*
Flux Kustomizations (`cvgen-apps` for the Deployment, `cvgen-canary` for
the gate), reconciling on independent schedules — plus a stale-artifact
re-apply. The Deployment flip and the gate flip weren't atomic, so one
analysis window ran new-spec-vs-old-gate.

**Fix.** Added a `cvgen.dev/rollout-nonce` pod-template annotation —
bumping it in git forces a fresh canary with zero functional change; one
bump cleared the stale `Failed`. (Kept permanently as the documented
"force a rollout" knob.)

**Lesson.** In GitOps, two files in one commit ≠ one atomic apply. Any
workflow that couples a workload change to a policy change must tolerate
the window where only one has landed.
