"""Operational HTTP server (background thread): liveness, readiness, and
Prometheus metrics. Kept off the event loop and separate from any app traffic.

- GET /livez   -> 200 while the process is up.
- GET /readyz  -> 200 when the readiness check passes, else 503.
- GET /metrics -> Prometheus exposition for VictoriaMetrics to scrape.
"""

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

ReadinessCheck = Callable[[], bool]


def start_ops_server(addr: str, readiness: ReadinessCheck | None = None) -> HTTPServer:
    port = int(addr.rsplit(":", 1)[1])

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if self.path == "/livez":
                self._send(200, b'{"status":"ok"}')
            elif self.path == "/readyz":
                ok = True
                if readiness is not None:
                    try:
                        ok = readiness()
                    except Exception:  # noqa: BLE001
                        ok = False
                body = b'{"status":"ready"}' if ok else b'{"status":"not ready"}'
                self._send(200 if ok else 503, body)
            elif self.path == "/metrics":
                self._send(200, generate_latest(), CONTENT_TYPE_LATEST)
            else:
                self._send(404, b'{"status":"not found"}')

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
