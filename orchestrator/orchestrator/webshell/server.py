"""Local-only HTTP server for the kiosk web UI.

Stdlib `http.server` on purpose -- same "no external deps unless
deliberately added" rule as the rest of `orchestrator/` (see its
README). Binds to 127.0.0.1 only; this is a single-user kiosk box, not
a service meant to be reachable from anywhere else.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import onboarding
from ..registry.db import AppRegistry
from . import api
from .state import ConnectionState

STATIC_DIR = Path(__file__).parent / "static"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def build_handler(state: ConnectionState, registry: AppRegistry, config_path: Path) -> type[BaseHTTPRequestHandler]:
    static_root = STATIC_DIR.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIOSWebShell/1"

        def log_message(self, fmt, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # kiosk box, no one is watching a terminal for this

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel_path: str) -> None:
            candidate = (static_root / rel_path).resolve()
            if candidate != static_root and static_root not in candidate.parents:
                self.send_error(404)
                return
            if not candidate.is_file():
                self.send_error(404)
                return
            body = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            if self.path in ("/", "/index.html"):
                self._send_static("index.html")
            elif self.path.startswith("/static/"):
                self._send_static(self.path[len("/static/") :])
            elif self.path == "/api/status":
                self._send_json(api.status_payload(state))
            elif self.path == "/api/apps":
                self._send_json(api.apps_payload(registry))
            elif self.path == "/api/choices":
                self._send_json(
                    {"choices": [{"id": c.id, "label": c.label, "kind": c.kind} for c in onboarding.CHOICES]}
                )
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            if self.path == "/api/prompt":
                body = self._read_json_body()
                text = (body.get("text") or "").strip()
                if not text:
                    self._send_json({"status": "error", "message": "empty prompt"}, status=400)
                    return
                self._send_json(api.prompt_payload(state, registry, text, config_path=config_path))
            else:
                self.send_error(404)

    return Handler


def build_server(
    state: ConnectionState,
    registry: AppRegistry,
    config_path: Path = onboarding.DEFAULT_CONFIG_PATH,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    handler_cls = build_handler(state, registry, config_path)
    return ThreadingHTTPServer((host, port), handler_cls)
