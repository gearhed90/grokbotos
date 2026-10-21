"""media.keys.* : hardware media keys delivered to apps.

sway sends Play/Pause/Next/Previous/Stop to `grokbot-os media-key KEY`,
which calls media.keys.press. Apps that hold media.keys.wait (a long
poll) get the key; the newest waiter wins, like a focused player.
When nobody is waiting, the CLI falls back to playerctl (MPRIS).
"""
import threading
import time

from .backends import BackendError

KEYS = ("play-pause", "play", "pause", "next", "previous", "stop")
_cond = threading.Condition()
_seq = 0
_last = None          # (seq, key, time)
_waiters = []         # tokens, newest last


def press(params):
    global _seq, _last
    key = params["key"]
    if key not in KEYS:
        raise BackendError("unknown key")
    with _cond:
        if not _waiters:
            return {"key": key, "delivered": False}
        _seq += 1
        _last = (_seq, key, time.time(), _waiters[-1])
        _cond.notify_all()
    return {"key": key, "delivered": True}


def wait(params):
    timeout = min(max(float(params.get("timeout", 25)), 0), 55)
    token = object()
    with _cond:
        start = _seq
        _waiters.append(token)
        try:
            end = time.time() + timeout
            while True:
                if _last and _last[0] > start and _last[3] is token:
                    return {"key": _last[1]}
                if _last and _last[0] > start:
                    start = _last[0]   # went to a newer player
                left = end - time.time()
                if left <= 0:
                    return {"key": None}
                _cond.wait(left)
        finally:
            _waiters.remove(token)


METHODS = {"media.keys.press": press, "media.keys.wait": wait}
