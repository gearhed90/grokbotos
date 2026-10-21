"""capture.status: screenshot folder and recent files (read-only).

Lists file names and sizes only; never returns image data.
"""
import os


def _dir():
    return os.environ.get("GROKBOT_SCREENSHOT_DIR") or os.path.join(
        os.path.expanduser("~"), "Pictures", "Screenshots")


def capture_status(params):
    d = _dir()
    files = []
    try:
        for name in os.listdir(d):
            if name.lower().endswith(".png"):
                st = os.stat(os.path.join(d, name))
                files.append((st.st_mtime, name, st.st_size))
    except OSError:
        pass
    files.sort(reverse=True)
    limit = params.get("limit", 10)
    return {"dir": d, "count": len(files),
            "recent": [{"name": n, "size_bytes": sz, "mtime": int(m)} for m, n, sz in files[:max(0, limit)]],
            "tools": {t: any(os.access(os.path.join(p, t), os.X_OK)
                             for p in os.environ.get("PATH", "").split(":") if p)
                      for t in ("grim", "slurp", "wl-copy")}}
