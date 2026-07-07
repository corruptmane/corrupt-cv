# ADR 0004: JetStream single-authority provisioning by the gateway

## Status

Accepted

## Context

The pipeline needs a stream (`CV_EVENTS`), durable and ephemeral consumers, and a KV bucket (model catalog). If every service created the entities it uses, definitions would be duplicated across two languages and could race or diverge (different retention, subjects, or limits depending on who boots first).

## Decision

The **gateway is the sole authority** for NATS topology. At boot it provisions the `CV_EVENTS` stream, its durable consumers, and the `model-catalog` KV bucket using idempotent `CreateOrUpdate*` calls, so restarts and config changes converge without manual migration. The Python services only **bind** to existing entities and fail fast with a clear error if they are missing.

## Consequences

- Topology is defined once, in one language, in one place; changing retention or subjects is a one-file change.
- Start order matters: workers require a booted gateway on first-ever startup. Compose encodes this implicitly (everything waits on core infra; the gateway boots quickly), and worker bind-failure messages make the dependency obvious.
- `CreateOrUpdate*` means the gateway can also *evolve* stream config in place — deliberate, since the gateway owns it.

## Alternatives considered

- **Each service provisions what it consumes** — rejected: duplicated definitions in Go and Python, races on first boot, drift over time.
- **Out-of-band provisioning (nats CLI / init container)** — rejected: another artifact to keep in sync; the gateway already has to know the topology to publish into it.
