# ADR 0009: Typst rendering via native sys.inputs JSON contract

## Status

Accepted

## Context

cv-generator turns a structured CV (protobuf) into a PDF. Typst compiles fast, embeds cleanly as a Python library (no LaTeX toolchain), and can receive data via `sys.inputs` without templating text files.

## Decision

- The structured CV is serialized to a **JSON document passed through Typst's native `sys.inputs`** mechanism; the template reads it with `json(...)`/`sys.inputs` access — no string interpolation into template source.
- **Nulls are preserved** in the JSON: the template dereferences every key and decides presentation, so the converter never drops or invents fields. The one semantic mapping lives at the boundary: `end_date == None` renders as **"Present"**.
- The template (`services/cv-generator/assets/cv.typ`) is **owned by cv-generator** and baked into its image at `TYPST_TEMPLATE_PATH`; it is a rendering concern, not a shared contract.

## Consequences

- Injection-safe by construction (data never becomes Typst source) and template errors are visible Typst compile errors pointing at real keys.
- Adding a CV field means: proto change, converter passes it through (nulls included), template decides how to show it — each layer's job is mechanical.
- Template iteration requires rebuilding only the cv-generator image.

## Alternatives considered

- **Text-templating the .typ source (Jinja et al.)** — rejected: escaping/injection hazards and unreadable diffs.
- **LaTeX** — rejected: image size, compile latency, dependency sprawl.
- **HTML→PDF (wkhtmltopdf/Chromium)** — rejected: heavyweight runtime and poor typographic control.
- **Dropping null keys from the JSON** — rejected: template would need existence checks everywhere; preserving keys keeps the contract total.
