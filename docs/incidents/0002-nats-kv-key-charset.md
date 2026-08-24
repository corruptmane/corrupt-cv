# 0002: NATS KV rejected the model-catalog keys

**Symptom.** Gateway crashed at startup seeding the catalog:
`nats: invalid key`.

**Root cause.** KV key charset is `[-/_=.a-zA-Z0-9]` — no colons. Keys
were `provider:model`.

**Fix.** Switched to `provider/model` everywhere (YAML, tests, e2e,
docs, proto comment + regen). Slash is legal and reads naturally as a
hierarchy.
