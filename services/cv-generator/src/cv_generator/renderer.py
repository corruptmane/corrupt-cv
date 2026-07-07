"""Typst rendering: one compiler per process, per-job data via sys.inputs."""

from pathlib import Path

import typst


class Renderer:
    """Compiles the CV template to PDF with the CV JSON injected as sys.inputs "data"."""

    def __init__(self, template_path: Path) -> None:
        self._compiler = typst.Compiler(template_path)

    def render(self, cv_json: str) -> bytes:
        result = self._compiler.compile(format="pdf", sys_inputs={"data": cv_json})
        if not isinstance(result, bytes):  # output=None guarantees bytes; guard the stub's union
            raise TypeError(f"typst compiler returned {type(result).__name__}, expected bytes")
        return result
