"""Append-only audit log (JSON lines, mode 0600, rotated at 5 MB)."""
import json
import os
import threading
import time

from . import paths

MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()


def record(**fields):
    path = paths.audit_path()
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    entry.update(fields)
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with _lock:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        try:
            if os.path.getsize(path) > MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
