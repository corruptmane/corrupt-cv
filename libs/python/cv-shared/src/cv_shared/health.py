"""Minimal ops HTTP server for k8s-style probes, run on a daemon thread.

Exposes /healthz (process liveness, always 200) and /readyz (200 when the
supplied readiness check passes, 503 otherwise).
"""

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthServer:
    def __init__(self, port: int, ready_check: Callable[[], bool]) -> None:
        self._ready_check = ready_check
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/healthz":
                    self._respond(200, b"ok")
                elif self.path == "/readyz":
                    if outer._ready_check():
                        self._respond(200, b"ready")
                    else:
                        self._respond(503, b"not ready")
                else:
                    self._respond(404, b"not found")

            def _respond(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass  # probe spam does not belong in service logs

        self._server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="ops-server", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
