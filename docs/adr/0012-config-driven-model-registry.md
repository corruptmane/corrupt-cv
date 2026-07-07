# 0012. Config-driven model registry

- **Status:** Accepted
- **Date:** 2026-06-18

## Context and forces

The form must let a user pick which model runs their generation. The v1 form had
a free-text `model` field: the user typed a raw model id and the gateway passed
it through, trusting the string matched the format each provider's SDK expects.
That is fragile — typos and wrong-format ids surface only as a provider error
deep in `ai-processor`, and the set of "blessed" models was implicit in code
(the per-provider defaults in `agent.py`).

Forces:

- **No raw-id guessing.** The user should choose from known-good models, not type
  a string and hope the format is right.
- **Change models without a code change.** Adding/removing a selectable model (or
  bumping a default) should not require editing Go and redeploying.
- **Validated server-side.** Whatever the browser sends must be checked before it
  reaches the bus; an unknown id should degrade gracefully, not fail the job.

## Decision

**A config-driven model registry.** `config/models.yaml` maps
`provider → [{id, label, default}]`; the gateway loads it at startup
(`internal/modelcfg`) from `MODELS_CONFIG_PATH` (mounted into the container, so it
is editable without a rebuild).

- The form renders a **dependent dropdown**: changing the provider issues
  `GET /models?provider=…` (HTMX) which returns the `<select>` of that provider's
  models (the `model_field` template); the page seeds with the default provider's
  list.
- On submit the gateway **resolves** `(provider, model)` against the registry —
  a valid id passes through, anything else falls back to the provider's default
  (`Registry.Resolve`). So the model on the bus is always one the registry blesses.
- `test` (the keyless deterministic provider) is just another registry entry.

## Alternatives considered (with why-not for each)

- **Keep the free-text `model` field.** Simplest, but no validation and no
  discoverability — the failure mode is a late provider error, and the valid set is
  invisible to the user. Rejected.
- **Hardcode a per-provider dropdown in the template/Go.** Removes the free-text
  problem but re-buries the model list in code: every change is a code edit +
  redeploy. Rejected in favour of the mounted YAML.
- **Runtime-editable registry (DB/Valkey-backed + admin endpoint).** Fully dynamic,
  no restart — but it adds an admin surface and storage for a list that changes
  rarely. Deferred: the YAML can graduate to this later behind the same
  `Registry` interface.

## Consequences (positive and negative/trade-offs)

Positive:

- **Validated, discoverable model choice**; an invalid id can never reach the bus.
- **Ops edit, not a code change** — update `config/models.yaml` and restart.
- A clean seam (`modelcfg.Registry`) to later back the registry by a DB/admin UI.

Negative / trade-offs:

- The registry is **load-at-startup**, so a model change needs a gateway restart
  (acceptable for v1; the deferred runtime-editable option removes this).
- The provider list itself is still fixed by the proto `Provider` enum; only the
  *models per provider* are config-driven.

## Sets up

- A natural place to attach per-model metadata later (context window, pricing,
  capability flags) and to drive the deferred billing/quotas off the same config.
