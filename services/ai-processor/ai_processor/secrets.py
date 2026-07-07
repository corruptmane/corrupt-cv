"""Reads the BYO API key transiently from Valkey via GETDEL (single use),
wrapped in a manual OTel CLIENT span (the redis instrumentor patches the
`redis` module, not `valkey`, so for one call a manual span is cleaner)."""

from typing import cast

import valkey.asyncio as valkey
from opentelemetry import trace
from opentelemetry.trace import SpanKind

_tracer = trace.get_tracer("ai_processor.secrets")


class SecretStore:
    def __init__(self, url: str) -> None:
        self._client = valkey.from_url(url, decode_responses=True)

    async def take(self, job_id: str) -> str | None:
        """Atomically fetch and delete the key. Returns None for keyless providers."""
        with _tracer.start_as_current_span(
            "valkey GETDEL",
            kind=SpanKind.CLIENT,
            attributes={"db.system": "valkey", "db.operation": "GETDEL"},
        ):
            # decode_responses=True yields str; the stub's bytes branch can't occur.
            return cast("str | None", await self._client.getdel(f"apikey:{job_id}"))

    async def close(self) -> None:
        await self._client.aclose()
