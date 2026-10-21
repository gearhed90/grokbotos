"""notifications.list: current notifications and Do Not Disturb (read-only).

Only app name, summary and urgency are returned, never the body, so a
caller with notifications.read cannot read message contents.
"""
import json

from . import procs

URGENCY = {0: "low", 1: "normal", 2: "critical"}


def _val(v):
    # makoctl < 1.9 wraps values as {"type": "s", "data": ...}
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def _parse(out):
    try:
        doc = json.loads(out)
    except ValueError:
        return None
    rows = doc
    if isinstance(doc, dict):
        rows = doc.get("data", [])
        if rows and isinstance(rows[0], list):
            rows = rows[0]
    if not isinstance(rows, list):
        return None
    res = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        g = lambda *ks: next((_val(r[k]) for k in ks if k in r), None)  # noqa: E731
        u = g("urgency")
        res.append({"id": g("id"), "app": g("app-name", "app_name"),
                    "summary": g("summary"),
                    "urgency": URGENCY.get(u, u) if isinstance(u, int) else u})
    return res


def _list(kind):
    for cmd in (["makoctl", kind, "-j"], ["makoctl", kind]):
        out = procs.run(cmd)
        if out:
            parsed = _parse(out)
            if parsed is not None:
                return parsed
    return []


def notifications_list(params):
    running = procs.running("mako")
    modes = (procs.run(["makoctl", "mode"]) or "").split() if running else []
    out = {"daemon_running": running, "dnd": "do-not-disturb" in modes,
           "notifications": _list("list") if running else []}
    if params.get("include_history"):
        out["history"] = _list("history") if running else []
    return out
