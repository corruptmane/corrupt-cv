# 0006. Multiprovider AI via PydanticAI

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The `ai-processor` service consumes `cv.*.requested` (`GenerationRequest`,
carrying `experience_text`, `job_description`, `contacts`, `provider`, `model`)
and must emit a `cv.{jobID}.structured` (`CVStructured`) whose body is a fully
typed CV. The canonical Pydantic CV models live in `libs/cvworker`
(`cv_worker/models.py`) — they are the single source of truth that both the bus
mapping and the Typst renderer rely on.

Forces:
- The output must be *structured and validated*, not free text — the renderer
  binds `CVStructured` natively, so an invalid CV is a hard failure.
- BYO API key handling (ADR on secrets): the key arrives per-request via
  `GETDEL apikey:{jobID}` in Valkey and must never hit the bus, Postgres, or
  logs. Whatever AI layer we pick must accept a per-call key, not a process-wide
  env var.
- We want to support several providers (OpenAI, Anthropic, Gemini, plus keyless
  local Ollama) without writing N bespoke JSON-coercion paths.
- CI and demos must run with **no key and no network** — the whole vertical
  slice (gateway → NATS → ai-processor → cv-generator → S3) has to be
  exercisable keyless.

## Decision

Use **PydanticAI** as the AI layer in `ai_processor/agent.py`:
`Agent(model, output_type=models.CV, system_prompt=SYSTEM_PROMPT)`, where
`output_type` is the Pydantic `CV` model. PydanticAI handles
tool/JSON-schema coercion and retries the model against our schema, so the
service receives a validated `models.CV` rather than raw text.

Provider selection is driven by the `Provider` enum on the wire
(`cv.v1`, `generation.proto`): `PROVIDER_OPENAI=1`, `PROVIDER_ANTHROPIC=2`,
`PROVIDER_GEMINI=3`, `PROVIDER_OLLAMA=4`, `PROVIDER_TEST=5`,
`PROVIDER_UNSPECIFIED=0`. `_live_model()` maps each to a PydanticAI `Model`:
- OpenAI → `OpenAIChatModel` (default `gpt-4o-mini`)
- Anthropic → `AnthropicModel` (default `claude-haiku-4-5`)
- Gemini → `GoogleModel` (default `gemini-2.0-flash`)
- Ollama → `OpenAIChatModel` against `OLLAMA_BASE_URL`
  (`http://...:11434/v1`, sentinel key `"ollama"`)

The per-request `api_key` (from Valkey) and `model` id flow as function
arguments into the provider constructor; provider/model travel on the bus, the
key does not.

`PROVIDER_TEST` (and `PROVIDER_UNSPECIFIED`) short-circuit `generate_cv()` to
`_demo_content()`, which builds deterministic, schema-valid `models.CVContent`
from the request with **no provider call and no network**. This is what makes
keyless CI/e2e and live demos possible.

The model produces **content only** (`CVContent`: summary, experience, education,
skills, projects, languages) — it is never sent, and never asked to produce, the
contact block. Only `experience_text` + `job_description` go into the prompt. The
processor then assembles the wire `CV` from that content plus the authoritative
form contacts (`mapping.content_to_proto(content, req.contacts)`). This saves
tokens and removes any chance of the model inventing identity data.

## Alternatives considered (with why-not for each)

- **Hand-rolled provider registry over raw SDKs (openai, anthropic, google).**
  Rejected: we'd own structured-output coercion, schema-retry, and per-provider
  JSON quirks for four providers, then keep it green as SDKs drift. PydanticAI
  already does this and pins to our `output_type`.
- **Raw provider SDKs with manual `json.loads` + `CV.model_validate`.**
  Rejected: no automatic re-ask on a schema miss, hand-rolled coercion, and four
  divergent code paths to test.
- **A separate mock provider service for keyless runs.** Rejected as
  overweight: `_demo_cv()` is an in-process function with zero infra, and
  `PROVIDER_TEST` keeps the *same* `generate_cv()` codepath under test.

## Consequences (positive and negative/trade-offs)

Positive:
- One thin agent file; adding a provider is one branch in `_live_model()`.
- `output_type=models.CV` means the service either gets a valid CV or raises —
  the failure surfaces as `cv.{jobID}.failed` rather than a malformed
  `structured` event.
- Keyless `PROVIDER_TEST` lets the full pipeline run in CI/demos with no
  secrets, and exercises the real publish/consume/render path.

Negative / trade-offs:
- The CV models extract from LLM-generated JSON, where enum values arrive as
  strings (`"NATIVE"`) and numbers may need coercion. The models therefore run in
  pydantic's **coercing** (non-`strict`) mode — `strict=True` rejects exactly these
  and made live extraction fail (`Exceeded maximum output retries`). The models are
  used only at this LLM boundary (the Typst path goes through proto), so coercion
  has no downside here; the trade-off is slightly looser internal typing in
  exchange for working live extraction.
- Default model ids (`gpt-4o-mini`, `claude-haiku-4-5`, `gemini-2.0-flash`,
  `llama3.2`) will age; they are overridable per-request via `req.model`.
- PydanticAI couples us to its provider/model abstractions; mitigated by the
  enum + `_live_model()` indirection at the seam.

## Sets up

- A clean place to add providers/models without touching the bus contract.
- Future per-provider observability: PydanticAI runs sit inside the OTLP trace
  already propagated via `traceparent` headers.
- Roadmap (not built here): Stripe-metered usage and saved profiles can key off
  the same `provider`/`model` selection without changing this layer.
