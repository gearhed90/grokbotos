"""The native consent prompt and camera/microphone use sessions.

prompt() runs the GTK layer-shell dialog (grokbot-consent) as a child
process and waits for the user's answer: "once", "always" or "deny".
One prompt at a time; a prompt that is not answered in TIMEOUT seconds,
or that cannot be shown (no Wayland session), counts as "deny".
The request text is passed on stdin as JSON, never on the command line.
"""
import glob
import json
import os
import subprocess
import threading
import time
import uuid

from . import paths, perms

TIMEOUT = 60
SESSION_MAX_S = 3600
_prompt_lock = threading.Lock()
_sessions = {}
_sess_lock = threading.Lock()


def _cmd():
    c = os.environ.get("GROKBOT_CONSENT_CMD")
    return c.split() if c else ["/usr/local/bin/grokbot-consent"]


def _env():
    env = dict(os.environ)
    if not env.get("WAYLAND_DISPLAY"):
        socks = sorted(os.path.basename(p) for p in glob.glob(os.path.join(paths.runtime_dir(), "wayland-*"))
                       if not p.endswith(".lock"))
        if socks:
            env["WAYLAND_DISPLAY"] = socks[0]
    return env


def prompt(principal, client, scope, method, description, summary, allow_always):
    """Returns (answer, detail). answer in once|always|deny."""
    ko, en = perms.SCOPES.get(scope, (scope, scope))
    req = {"principal": principal, "client": client, "scope": scope, "scope_ko": ko, "scope_en": en,
           "method": method, "description": description, "summary": summary,
           "allow_always": bool(allow_always), "timeout": TIMEOUT}
    with _prompt_lock:
        try:
            r = subprocess.run(_cmd(), input=json.dumps(req, ensure_ascii=False), capture_output=True,
                               text=True, timeout=TIMEOUT + 5, env=_env())
        except subprocess.TimeoutExpired:
            return "deny", "timeout"
        except OSError:
            return "deny", "no_prompt"
    ans = (r.stdout or "").strip().splitlines()[-1:] or [""]
    ans = ans[0]
    if r.returncode != 0 or ans not in ("once", "always", "deny"):
        return "deny", "no_prompt" if r.returncode != 0 else "bad_answer"
    if ans == "always" and not allow_always:
        ans = "once"
    return ans, "user"


# ---------------- camera / microphone sessions ----------------

def _expire():
    now = time.time()
    for k in [k for k, s in _sessions.items() if s["expires"] <= now]:
        del _sessions[k]


def session_start(kind, principal, client, purpose, duration_s):
    duration_s = max(10, min(SESSION_MAX_S, int(duration_s)))
    sid = uuid.uuid4().hex[:16]
    with _sess_lock:
        _expire()
        _sessions[sid] = {"id": sid, "kind": kind, "principal": principal, "client": client,
                          "purpose": purpose, "started": time.time(),
                          "expires": time.time() + duration_s}
        return _public(_sessions[sid])


def session_stop(sid, principal):
    with _sess_lock:
        _expire()
        s = _sessions.get(sid)
        if s is None:
            return False
        if s["principal"] != principal and not perms.is_local(principal):
            raise PermissionError("not your session")
        del _sessions[sid]
        return True


def sessions():
    with _sess_lock:
        _expire()
        return [_public(s) for s in sorted(_sessions.values(), key=lambda s: s["started"])]


def _public(s):
    return {"id": s["id"], "kind": s["kind"], "principal": s["principal"], "client": s["client"],
            "purpose": s["purpose"], "started": int(s["started"]), "expires": int(s["expires"])}
