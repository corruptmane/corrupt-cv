# 0007. Typst PDF rendering with native sys_inputs binding

- **Status:** Accepted
- **Date:** 2026-06-17

## Context and forces

The `cv-generator` service consumes `cv.*.structured` (`CVStructured`, protobuf
binary), renders a PDF, uploads it to S3 at `pdfs/{jobID}.pdf`, and emits
`cv.*.completed`. We need a way to turn a structured CV into a typeset PDF that:

- works inside a slim Python 3.13 container with **no system-level install
  step** (the workers are meant to be thin and reproducible);
- builds cross-platform — the dev loop is macOS, CI/runtime is Linux;
- keeps a clean separation between **data** (the structured CV) and
  **presentation** (the document layout), so the user can drop in a richer
  template later without touching service code;
- doesn't introduce a second templating language/runtime to reason about.

The input is the canonical Pydantic CV model (defined in `libs/cvworker`),
mapped from the proto and handed to the renderer as a plain `dict`.

## Decision

Render with **Typst via the `typst` PyPI package** (`typst>=0.11`, see
`services/cv-generator/pyproject.toml`). The wheel bundles the Typst compiler,
so there is **no `apt install` / system dependency** in the Dockerfile.

Bind data with Typst's **native `sys.inputs` mechanism**, not a text-templating
pass. `render_pdf` in `services/cv-generator/cv_generator/render.py` does:

```python
typst.compile(str(_TEMPLATE), sys_inputs={"data": json.dumps(cv)})
```

and the template at `services/cv-generator/cv_generator/templates/cv.typ`
decodes it itself:

```typst
#let data = json(bytes(sys.inputs.at("data")))
```

The CV crosses the boundary as a single JSON string under the `data` key; the
`.typ` file owns all layout logic (header, summary, experience, education,
skills, projects, languages). The renderer feeds it a **complete dict** — every
field present, `None` for unset optionals and `[]` for empty lists
(`mapping.proto_to_dict`) — so the template's `!= none` / `.len() > 0` guards hold.
The user's production `cv.typ` is in place; iterating on it is a no-code-change
operation.

## Alternatives considered (with why-not for each)

- **Jinja2-rendered `.typ` source** — spiked. Render a `.typ` string with Jinja2,
  then compile it. Rejected: it puts CV data into the *source text*, so we'd
  hand-escape every Typst-significant character to avoid syntax injection and
  broken output; it adds a second templating runtime on top of Typst's own; and
  it couples the renderer to template structure. Native `sys.inputs` does the
  same job with one language and no escaping surface.
- **LaTeX (e.g. via a `tectonic`/TeX toolchain)** — rejected: heavy system
  install, slow cold builds, and a fragile, error-prone escaping/packaging
  story for an automated pipeline. Contradicts the no-system-install goal.
- **HTML → PDF (headless browser / wkhtmltopdf)** — rejected: drags in a
  browser or native binary (and the cross-platform/container weight that
  implies), and gives weaker control over print typography (pagination, margins)
  than a document compiler.

## Consequences (positive and negative/trade-offs)

Positive:

- No system dependency: `pip`/`uv` install of one wheel is the whole toolchain;
  the Dockerfile stays slim and the dev loop builds on macOS and Linux alike.
- Clean data/presentation split: JSON in via `sys.inputs.data`, layout owned by
  `cv.typ`. Iterating on the template is a no-code-change operation.
- No escaping/injection surface: the CV is decoded as data (`json(bytes(...))`),
  never spliced into source, so arbitrary user/LLM text can't break the document.
- Single templating language to learn and maintain (Typst), not Typst + Jinja2.

Negative / trade-offs:

- Template authors must learn Typst markup, and the data contract is implicit —
  the `.typ` reads keys (`personal_info`, `experience`, `skills`, ...) defensively
  with `.at(..., default: ...)`; a field rename in the Pydantic model can
  silently produce an empty section rather than an error.
- Layout/styling correctness isn't type-checked; it's verified by rendering
  (`tests/test_render.py`) and eyeballing output.
- We're pinned to Typst's feature set and the `typst` wheel's release cadence.

## Sets up

The deferred richer/branded template the user will supply drops in as a `.typ`
swap with zero service changes. It also keeps `cv-generator` a stateless,
single-purpose worker (consume `structured` → render → upload → emit
`completed`), consistent with the gateway being the sole Postgres writer.
