"""Render a CV dict to PDF using the bundled Typst compiler. The CV JSON is
passed via `sys.inputs.data` and decoded inside the template (no Jinja2)."""

import json
from pathlib import Path
from typing import Any

import typst

_TEMPLATE = Path(__file__).resolve().parent / "templates" / "cv.typ"


def render_pdf(cv: dict[str, Any]) -> bytes:
    return typst.compile(str(_TEMPLATE), sys_inputs={"data": json.dumps(cv)})
