"""In-memory, thread-safe log ring buffer feeding the shell UI's live log
panel.

Added after real boot testing repeatedly hit the same problem: a
long-running background operation (CLI install, `claude login`, a stuck
connection) with nothing on screen but a static "연결 중..." -- no way to
tell what was actually happening. Every layer that shells out to a real
CLI (providers/cli_subprocess.py, providers/local_ollama.py) now accepts
an optional `log` callable; this is what gets passed in.

`/api/logs` long-polls against `wait_for_more()`: a GET blocks (up to a
timeout) until either new entries exist or the timeout elapses, so the
frontend gets near-real-time updates without a websocket.
"""

from __future__ import annotations

import threading
from collections import deque


class LogBuffer:
    def __init__(self, maxlen: int = 500) -> None:
        self._condition = threading.Condition()
        self._entries: deque[tuple[int, str]] = deque(maxlen=maxlen)
        self._next_id = 0

    def append(self, line: str) -> None:
        with self._condition:
            self._entries.append((self._next_id, line))
            self._next_id += 1
            self._condition.notify_all()

    def since(self, after_id: int) -> list[tuple[int, str]]:
        with self._condition:
            return [entry for entry in self._entries if entry[0] > after_id]

    def wait_for_more(self, after_id: int, timeout: float = 25.0) -> list[tuple[int, str]]:
        with self._condition:
            self._condition.wait_for(lambda: any(i > after_id for i, _ in self._entries), timeout=timeout)
            return [entry for entry in self._entries if entry[0] > after_id]
