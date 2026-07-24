# 15. Deployment alerting through a single Alertmanager → Telegram pipe

Date: 2026-07-24

## Status

Accepted

## Context

The rollback drill (ADR 0012's canary gates) proved Flagger reverts a bad
release autonomously — but nothing notified anyone. The homelab's vmalert
ran with `notifier.blackhole: true`, and Flagger's native `AlertProvider`
supports only Slack/Teams/Discord/Rocket/GChat — no Telegram, which is the
channel we want. Flux reconciliation failures (broken manifests, image
automation errors) were equally silent.

## Decision

One receiver, two feeders, failures only:

- **Alertmanager** (the victoria-metrics-k8s-stack component, previously
  disabled) becomes the single notification pipe, with a Telegram receiver.
  Its entire `alertmanager.yaml` is rendered by an External Secrets
  template from two SSM parameters (`/homelab/telegram-bot-token`,
  `/homelab/telegram-chat-id`), so neither the token nor the chat id
  appears in either git repo. The always-firing `Watchdog` heartbeat and
  `severity: info` alerts route to a blackhole receiver.
- **Flagger rollbacks** ride the metrics path, per Flagger's own
  documentation for unsupported channels: the flagger chart's `podMonitor`
  is enabled (the VM operator converts it for vmagent), and a `VMRule` in
  the `cvgen` namespace fires `CanaryRollback` (critical) on
  `flagger_canary_status > 1` held for 1m. The status stays failed until a
  new revision rolls out, so the alert re-fires every 12h while production
  sits on a rolled-back release — deliberate: a silent stale rollback is
  the failure mode this ADR exists to prevent.
- **Flux failures** go through notification-controller's `alertmanager`
  provider into the same pipe: an `Alert` with `eventSeverity: error`
  watches GitRepositories, Kustomizations, HelmRepositories, and the image
  automation kinds fleet-wide. HelmReleases are not listed directly; the
  Kustomizations that apply them use `wait`, so an unhealthy release fails
  its Kustomization.

Ownership follows the established split: the cvgen-specific pieces
(`VMRule`, flagger `podMonitor`) live in this repo under `deploy/k8s/`;
the shared pipe (Alertmanager, ESO template, Flux Provider/Alert) lives in
the homelab fleet repo.

## Consequences

- A canary rollback or a failed Flux reconciliation lands in Telegram
  within roughly a scrape-plus-evaluation interval; promotions and routine
  events stay silent.
- Un-blackholing vmalert also activates the k8s-stack's built-in
  node/kube-state rules at warning/critical — cluster problems unrelated
  to cvgen now notify too, tunable in the ESO-templated routes.
- The alerting chain shares the ESO/SSM secret machinery from ADR 0013;
  rotating the bot token is an SSM update plus a refresh interval.
