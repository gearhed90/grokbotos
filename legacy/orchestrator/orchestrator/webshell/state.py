"""Thread-safe connection state shared between HTTP handler threads.

`/api/connect` runs the actual login flow (which blocks on a real
subprocess, potentially for minutes while a browser OAuth flow
completes) on a background thread so the HTTP server keeps answering
`/api/status` polls in the meantime. This is the object both sides touch.
"""

from __future__ import annotations

import threading

from ..providers.base import LLMProvider


class ConnectionState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.provider: LLMProvider | None = None
        self.choice_id: str | None = None
        self.connecting_choice_id: str | None = None
        self.error: str | None = None
        self.needs_token: bool = False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "connected": self.provider is not None,
                "choice_id": self.choice_id,
                "connecting": self.connecting_choice_id,
                "error": self.error,
                "needs_token": self.needs_token,
            }

    def start_connecting(self, choice_id: str) -> None:
        with self._lock:
            self.connecting_choice_id = choice_id
            self.error = None
            self.needs_token = False

    def set_connected(self, choice_id: str, provider: LLMProvider) -> None:
        with self._lock:
            self.provider = provider
            self.choice_id = choice_id
            self.connecting_choice_id = None
            self.error = None
            self.needs_token = False

    def set_error(self, message: str, needs_token: bool = False) -> None:
        with self._lock:
            self.connecting_choice_id = None
            self.error = message
            self.needs_token = needs_token
