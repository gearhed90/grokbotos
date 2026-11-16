#!/usr/bin/env python3
"""novad - Cypher's on-screen voice and hands for grokbotos (stdlib only).

There is no separate chat assistant: talking to the avatar (typed or by voice) is
talking to Cypher. The system prompt is Cypher's persona and live state
(cypher_link.system_prompt: mood, drives, journal, phone replies, memories), and
every turn goes back into Cypher's journal through cypherd (cypher_link.record_turn).
Cypher's locked limits and approval rules still apply: nothing said here approves
an account request or changes a limit. The internal names (novad, nova-shell,
NOVA_* settings, ~/.config/grokbot/nova-voice.json) are kept so sway rules, the
lock screen and the toggle keep working.

Serves shell.html on http://127.0.0.1:PORT/ and handles prompts via the xAI
chat completions API with a small allowlisted toolset. No shell-exec tool.
Key: /etc/grokbot/xai_key (root-owned, group grokbot, mode 0640; set with
sudo grokbot-set-xai-key), else ~/.config/grokbot/xai_key (mode 600). Never logged.
"""
import json, os, re, shutil, stat, subprocess, sys, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import avatar_shapes   # avatar shape/color choice (~/.config/grokbot/avatar.json); nova_native watches the file
import cypher_link     # the conversation is Cypher's: persona, state, journal (see module doc)

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("NOVA_PORT", "8765"))
API_BASE = os.environ.get("NOVA_API_BASE", "https://api.x.ai/v1").rstrip("/")
MODEL = os.environ.get("NOVA_MODEL", "grok-4.7")
KEY_FILE = os.path.expanduser(os.environ.get("NOVA_KEY_FILE", "~/.config/grokbot/xai_key"))
# System key, set by the admin. NOVA_SYS_KEY_FILE="" turns it off (tests).
SYS_KEY_FILE = os.environ.get("NOVA_SYS_KEY_FILE", "/etc/grokbot/xai_key")
WEB_USERJS = os.environ.get("NOVA_WEB_USERJS", os.path.join(HERE, "nova-web-user.js"))
DRY_RUN = os.environ.get("NOVA_DRY_RUN") == "1"   # test mode: launches are logged, not run
HISTORY_MAX = 12          # messages kept (user/assistant only)
MAX_TOOL_ROUNDS = 4

os.environ.setdefault("TZ", "America/New_York")
time.tzset()

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)

# ---------- key ----------
class KeyError_(Exception): pass

def _sys_key():
    """The admin-set key, if present and safely owned: root:root or root:<our group>,
    no world bits, no group write."""
    if not SYS_KEY_FILE:
        return None
    try:
        st = os.stat(SYS_KEY_FILE)
    except OSError:
        return None
    mode = stat.S_IMODE(st.st_mode)
    if st.st_uid != 0 or mode & 0o027 or st.st_gid not in (0, os.getgid(), *os.getgroups()):
        raise KeyError_("badsys")
    try:
        with open(SYS_KEY_FILE) as f:
            return f.read().strip() or None
    except PermissionError:
        raise KeyError_("badsys")

def key_present():
    return bool(SYS_KEY_FILE and os.path.exists(SYS_KEY_FILE)) or os.path.exists(KEY_FILE)

def read_key():
    k = _sys_key()
    if k:
        return k
    try:
        st = os.stat(KEY_FILE)
    except FileNotFoundError:
        raise KeyError_("nokey")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise KeyError_("badperm")
    with open(KEY_FILE) as f:
        k = f.read().strip()
    if not k:
        raise KeyError_("nokey")
    return k

# ---------- tools ----------
def launch(argv):
    if DRY_RUN:
        log("DRY-RUN launch:", json.dumps(argv))
        return
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)

def seed_web_profile(prof):
    """Copy the shipped nova-web prefs (fast start, ffmpeg H.264) into the profile's user.js."""
    try:
        with open(WEB_USERJS, "rb") as f:
            data = f.read()
        dst = os.path.join(prof, "user.js")
        try:
            with open(dst, "rb") as f:
                if f.read() == data:
                    return
        except OSError:
            pass
        with open(dst + ".tmp", "wb") as f:
            f.write(data)
        os.replace(dst + ".tmp", dst)
    except OSError as e:
        log("nova-web prefs not seeded:", e.__class__.__name__)

def url_launcher():
    # grokbot-webapp takes an app id, not a URL, so web pages open in a
    # dedicated Firefox profile window that sway raises to fullscreen.
    prof = os.path.expanduser("~/.local/share/grokbot/nova-web-profile")
    os.makedirs(prof, exist_ok=True)
    seed_web_profile(prof)
    return ["firefox", "--name", "nova-web", "--profile", prof, "--new-window"]

def raise_web():
    if DRY_RUN:
        return
    subprocess.Popen(["sh", "-c", "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; swaymsg -q '[app_id=\"nova-web\"] focus, fullscreen enable' && exit 0; done"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)

def t_open_url(url):
    u = urlparse(str(url).strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return {"ok": False, "error": "only http(s) URLs are allowed"}
    launch(url_launcher() + [u.geturl()])
    raise_web()
    return {"ok": True, "opened": u.geturl()}

# ---------- grokbotd (OS service) client ----------
GBD_SOCK = os.environ.get("GROKBOT_API_SOCK") or os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "grokbot", "api.sock")
GBD_WRITES = {"audio.set", "display.set_brightness", "network.wifi.connect", "power.action"}
class GbdError(Exception): pass
_rpc_id = 0

def rpc(method, params=None, timeout=60):
    """JSON-RPC over grokbotd's unix socket. Writes are skipped in DRY_RUN.
    Writes may open grokbotd's own consent dialog (built-in local write=ask)."""
    global _rpc_id
    if DRY_RUN and method in GBD_WRITES:
        log("DRY-RUN rpc:", method, json.dumps(params or {}))
        return {"dry_run": True}
    import socket
    _rpc_id += 1
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout)
    try:
        s.connect(GBD_SOCK)
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": _rpc_id, "method": method,
                               "params": params or {}, "x-client": {"name": "Nova (novad)"}}) + "\n").encode())
        f = s.makefile("rb"); r = json.loads(f.readline() or b"{}")
    except (OSError, ValueError) as e:
        raise GbdError("grokbotd unavailable (%s)" % type(e).__name__)
    finally:
        s.close()
    if "error" in r:
        e = r["error"]
        raise GbdError("not allowed (declined)" if e.get("code") == -32001 else str(e.get("message", "error"))[:200])
    return r.get("result", {})

def audit(tool, args, outcome, via="direct"):
    safe = {k: v for k, v in (args or {}).items() if k in ("ssid", "name", "action", "percent", "change", "muted", "event", "secs", "chars", "shape", "color", "end")}
    log("AUDIT", json.dumps({"tool": tool, "args": safe, "via": via, "outcome": outcome}))

def run_ro(argv, timeout=6):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""

# ---------- apps ----------
SYS_APPS = os.environ.get("NOVA_SYS_APPS", "/usr/share/grokbot/webapps")
USER_APPS = os.path.expanduser(os.environ.get("NOVA_USER_APPS", "~/.local/share/grokbot/installed"))
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")

def installed_apps():
    """{name: app_id} from installed manifests, plus firefox. Never nova-shell."""
    apps = {}
    try:
        for d in sorted(os.listdir(SYS_APPS)):
            if ID_RE.match(d) and os.path.isfile(os.path.join(SYS_APPS, d, "manifest.json")):
                apps[d] = "grokbot-webapp-" + d
    except OSError:
        pass
    try:
        for fn in sorted(os.listdir(USER_APPS)):
            m = re.match(r"^webapp\.([a-z][a-z0-9-]{0,30})\.json$", fn)
            if m: apps[m.group(1)] = "grokbot-webapp-" + m.group(1)
    except OSError:
        pass
    apps["firefox"] = "firefox"
    apps["onshape_pad"] = "nova-cadpad"   # Onshape button pad (cadpad.py)
    apps["terminal"] = "grokbot-term"     # build 14b: a foot terminal on its own workspace (grokbot-term; Super+Enter)
    apps.pop("nova-shell", None)
    return apps

CLOSABLE_EXTRA = {"web": "nova-web"}   # pages Nova opened with open_url

APP_ALIASES = {"foot": "terminal", "term": "terminal", "shell": "terminal", "console": "terminal"}

def t_open_app(name):
    apps = installed_apps(); n = str(name).strip().lower(); n = APP_ALIASES.get(n, n)
    if n not in apps:
        return {"ok": False, "error": "app not allowed", "allowed": sorted(apps)}
    if n == "firefox":
        launch(["firefox", "--new-window"])
    elif n == "onshape_pad":
        launch([sys.executable, os.path.join(HERE, "cadpad.py"), "--fullscreen"])
    elif n == "terminal":
        launch(["/usr/local/bin/grokbot-term"])
    else:
        launch(["/usr/local/bin/grokbot-webapp", n])
    return {"ok": True, "opened": n}

def close_target(name):
    n = str(name).strip().lower(); n = APP_ALIASES.get(n, n)
    app_id = {**installed_apps(), **CLOSABLE_EXTRA}.get(n)
    if not app_id or app_id == "nova-shell":
        return None, {"ok": False, "error": "app not allowed", "allowed": sorted({**installed_apps(), **CLOSABLE_EXTRA})}
    wins = [w for w in rpc("windows.list").get("windows", []) if w.get("app_id") == app_id]
    if not wins:
        return None, {"ok": False, "error": n + " is not open"}
    return (n, app_id, [int(w["id"]) for w in wins]), None

def do_close(n, app_id, ids):
    for i in ids:   # by sway con_id, after re-checking it still belongs to this app
        if app_id == "nova-shell": break
        if DRY_RUN: log("DRY-RUN swaymsg kill con_id", i); continue
        subprocess.run(["swaymsg", "-q", "[con_id=%d app_id=\"%s\"] kill" % (i, app_id)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    return {"ok": True, "closed": n}

# ---------- volume / brightness ----------
def t_get_audio():
    o = (rpc("audio.status").get("output") or {})
    return {"ok": True, "volume_percent": o.get("volume_percent"), "muted": o.get("muted")}

def _target(cur, percent, change):
    if percent not in (None, ""):
        v = int(percent)
    elif change not in (None, ""):
        v = int(cur) + int(change)
    else:
        return None
    return v

def t_get_brightness():
    devs = rpc("display.brightness").get("devices") or []
    return {"ok": True, "percent": devs[0]["percent"] if devs else None}

# ---------- wifi ----------
def saved_ssids():
    if DRY_RUN:
        return set(filter(None, os.environ.get("NOVA_TEST_SAVED", "").split(",")))
    out = set()
    for line in run_ro(["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"]).splitlines():
        u, _, ty = line.partition(":")
        if ty == "802-11-wireless" and re.match(r"^[0-9a-f-]{36}$", u):
            s = run_ro(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", u]).strip()
            if s: out.add(s)
    return out

def t_wifi_status():
    nets = rpc("network.wifi.list").get("networks", [])
    saved = saved_ssids()
    return {"ok": True, "connected": next((n["ssid"] for n in nets if n.get("in_use")), None),
            "networks": [{"ssid": n["ssid"], "signal": n.get("signal"),
                          "open": not n.get("security"), "saved": n["ssid"] in saved} for n in nets[:12]]}

# ---------- system ----------
def temperature_c():
    base = os.environ.get("NOVA_THERMAL", "/sys/class/thermal")
    try:
        for z in sorted(os.listdir(base)):
            if z.startswith("thermal_zone"):
                return round(int(open(os.path.join(base, z, "temp")).read()) / 1000, 1)
    except (OSError, ValueError):
        pass
    return None

def t_system_info():
    info = {"time": time.strftime("%A %Y-%m-%d %H:%M %Z")}
    try:
        nets = rpc("network.wifi.list").get("networks", [])
        info["wifi_ssid"] = next((n["ssid"] for n in nets if n.get("in_use")), None) or "not connected"
    except GbdError:
        info["wifi_ssid"] = "unknown"
    try:
        bats = rpc("power.status").get("batteries") or []
        info["battery"] = ("%s%%" % bats[0].get("percent", bats[0].get("capacity", "?"))) if bats else "none (mains power)"
    except GbdError:
        info["battery"] = "unknown"
    try:
        disks = rpc("system.resources").get("disks", [])
        info["storage"] = [{"mount": d["mount"], "free_gb": round(d["free_bytes"] / 1e9, 1),
                            "total_gb": round(d["total_bytes"] / 1e9, 1)} for d in disks if d["mount"] != "/"]
    except (GbdError, KeyError, TypeError):
        info["storage"] = "unknown"
    info["cpu_temp_c"] = temperature_c()
    return info

def t_updates_status():
    u = rpc("update.status")   # read-only; never update.check/apply
    b = u.get("booted") or {}
    last = u.get("last") or {}
    return {"ok": True, "version": b.get("version"), "update_available": u.get("available"),
            "available_version": u.get("available_version"), "staged": bool(u.get("staged")),
            "restart_needed": u.get("restart_needed"), "last_check_ok": last.get("ok"),
            "note": "Cypher only reads update status; installing updates is done in Settings."}

# ---------- confirmations ----------
PENDING = {}; plock = threading.Lock(); CONFIRM_TTL = int(os.environ.get("NOVA_CONFIRM_TTL", "60"))

def make_pending(tool, args, text, run, physical=False, ttl=None):
    """A Yes/No the user answers on the deck. physical=True (power_off): only a click on Confirm in the
    avatar app, sent over the owner-only confirm socket, can say yes; HTTP, voice and Enter cannot."""
    import secrets
    pid = secrets.token_urlsafe(12)
    ttl = int(ttl or CONFIRM_TTL)
    with plock:
        now = time.time()
        for k in [k for k, v in PENDING.items() if v["exp"] < now]: del PENDING[k]
        PENDING[pid] = {"tool": tool, "args": args, "text": text, "run": run, "exp": now + ttl, "physical": bool(physical)}
    audit(tool, args, "pending")
    r = {"ok": False, "pending": True, "confirm_id": pid, "question": text, "ttl": ttl}
    if physical:
        r.update(physical=True, yes_label="Confirm", no_label="Cancel")
    return r

def confirm(pid, yes, physical=False):
    r = _confirm(pid, yes, physical)
    try:
        cypher_link.record_turn("yes" if yes else "no", r.get("reply") or r.get("text") or "", "typed",
                                [{"tool": r.pop("_tool", "?"), "args": r.pop("_args", {}), "outcome": r.get("error") or ("ok" if yes else "declined")}],
                                "confirm")
    except Exception as e:
        log("cypher link:", type(e).__name__)
    r.pop("_tool", None); r.pop("_args", None)
    return r

def _confirm(pid, yes, physical=False):
    with plock:
        p = PENDING.get(str(pid))
        if p and p.get("physical") and yes and not physical:
            # build 14: power_off needs the Confirm click on the deck; a yes from anywhere else is refused and
            # the dialog stays up (Cancel or the 30 s timeout still close it).
            audit(p["tool"], p["args"], "refused: needs the on-screen Confirm")
            return {"error": "needs_click", "text": "Only the Confirm button on Cypher's screen can do that.",
                    "_tool": p["tool"], "_args": p["args"]}
        p = PENDING.pop(str(pid), None)   # single use
    if not p:
        return {"error": "gone", "text": "That request expired or was already answered."}
    tag = {"_tool": p["tool"], "_args": p["args"]}
    if p["exp"] < time.time():
        audit(p["tool"], p["args"], "expired")
        return {"error": "expired", "text": "That request expired. Ask me again.", **tag}
    if not yes:
        audit(p["tool"], p["args"], "declined")
        return {"reply": "Okay, I won't.", **tag}
    try:
        res = p["run"]()
        audit(p["tool"], p["args"], "ok", via="confirmed")
        return {"reply": res, **tag}
    except (GbdError, subprocess.SubprocessError, OSError) as e:
        audit(p["tool"], p["args"], "error: " + str(e)[:80], via="confirmed")
        return {"error": "action", "text": "That didn't work: " + str(e)[:120], **tag}

# ---------- power_off (build 14) ----------
# Zack: "power down" in the deck chat -> the model calls power_off -> a Confirm/Cancel dialog on the deck's
# own screen (30 s, then it cancels itself) -> only a click on Confirm, sent by the avatar app over
# CONFIRM_SOCK (owner-only unix socket, peer uid checked), runs it. Then: a shutdown request file for
# cypherd (it journals "shutdown requested by Zack" on its way down), a clean `systemctl --user stop
# cypherd` (state saved, lease released as deck_stopped so Alpha takes over), and `systemctl poweroff`,
# allowed for the grokbot user by one polkit rule (50-grokbot-cypher-poweroff.rules: power-off only).
# cypherd itself has no power action, so autonomous ticks and the Alpha standby can never reach this.
POWER_OFF_TTL = int(os.environ.get("NOVA_POWER_OFF_TTL", "30"))
POWER_OFF_Q = "Shut Cypher down now?"
CONFIRM_SOCK = os.environ.get("NOVA_CONFIRM_SOCK") or os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "nova", "confirm.sock")

def power_off_pending():
    return make_pending("power_off", {"action": "poweroff"}, POWER_OFF_Q, do_power_off, physical=True, ttl=POWER_OFF_TTL)

def _sysctl(argv, timeout):
    if DRY_RUN:
        log("DRY-RUN", " ".join(argv)); return 0
    return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode

def do_power_off():
    cypher_link.request_shutdown()
    _sysctl(["systemctl", "--user", "stop", "cypherd.service"], 45)     # saves state, journals, hands off to Alpha
    rc = _sysctl(["systemctl", "poweroff"], 20)
    if rc != 0:
        _sysctl(["systemctl", "--user", "start", "cypherd.service"], 20)  # never leave him off without a shutdown
        raise OSError("the shutdown was refused (rc %d)" % rc)
    return "Shutting down. Alpha keeps me going until the deck is back."

def serve_confirm_socket():
    """The avatar app's Confirm/Cancel clicks: one JSON line {"id", "yes", "via": "click"} per connection.
    Owner-only (0700 dir, 0600 socket, peer uid must be ours)."""
    import socketserver, socket as _s, struct
    d = os.path.dirname(CONFIRM_SOCK)
    os.makedirs(d, mode=0o700, exist_ok=True); os.chmod(d, 0o700)
    try: os.unlink(CONFIRM_SOCK)
    except FileNotFoundError: pass
    class CH(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                cred = self.request.getsockopt(_s.SOL_SOCKET, _s.SO_PEERCRED, struct.calcsize("3i"))
                if struct.unpack("3i", cred)[1] != os.getuid():
                    return
                b = json.loads(self.rfile.readline(1024) or b"{}")
                if b.get("via") != "click":
                    r = {"error": "bad", "text": "clicks only"}
                else:
                    r = confirm(str(b.get("id"))[:64], b.get("yes") is True, physical=True)
            except (ValueError, OSError, TypeError) as e:
                r = {"error": "bad", "text": type(e).__name__}
            try: self.wfile.write((json.dumps(r) + "\n").encode())
            except OSError: pass
    old = os.umask(0o177)
    try:
        srv = socketserver.ThreadingUnixStreamServer(CONFIRM_SOCK, CH)
    finally:
        os.umask(old)
    os.chmod(CONFIRM_SOCK, 0o600)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# ---------- tool dispatch ----------
def _int(v, lo, hi, name):
    if v in (None, ""): return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not lo <= v <= hi:
        raise ValueError(name + " must be a whole number from %d to %d" % (lo, hi))
    return int(v)

def call_tool(name, a):
    if not isinstance(a, dict): a = {}
    try:
        if name == "open_url":
            r = t_open_url(a.get("url", ""))
        elif name == "open_app":
            r = t_open_app(a.get("name", ""))
        elif name == "close_app":
            tgt, err = close_target(a.get("name", ""))
            if err: r = err
            else:
                n, app_id, ids = tgt
                r = make_pending("close_app", {"name": n}, "Close %s?" % n,
                                 lambda: (do_close(n, app_id, ids), "Closed %s." % n)[1])
        elif name == "system_info":
            r = t_system_info()
        elif name == "updates_status":
            r = t_updates_status()
        elif name == "get_volume":
            r = t_get_audio()
        elif name == "set_volume":
            pct = _int(a.get("percent"), 0, 100, "percent"); ch = _int(a.get("change"), -100, 100, "change")
            muted = a.get("muted")
            if muted is not None and not isinstance(muted, bool): raise ValueError("muted must be true or false")
            cur = t_get_audio()["volume_percent"] or 0
            tgt = _target(cur, pct, ch)
            params = {"target": "output"}
            if tgt is not None: params["volume_percent"] = max(0, min(100, tgt))
            if muted is not None: params["muted"] = muted
            if len(params) == 1: raise ValueError("give percent, change or muted")
            def run(params=params):
                st = rpc("audio.set", params)
                return "Volume set" + (" to %d%%" % params["volume_percent"] if "volume_percent" in params else "") + \
                       ("" if "muted" not in params else (", muted" if params["muted"] else ", unmuted")) + "."
            if "volume_percent" in params and abs(params["volume_percent"] - cur) > 50:
                r = make_pending("set_volume", {"percent": params["volume_percent"]},
                                 "Change volume from %d%% to %d%%?" % (cur, params["volume_percent"]), run)
            else:
                r = {"ok": True, "result": run()}
        elif name == "get_brightness":
            r = t_get_brightness()
        elif name == "set_brightness":
            pct = _int(a.get("percent"), 1, 100, "percent"); ch = _int(a.get("change"), -100, 100, "change")
            cur = t_get_brightness()["percent"] or 0
            tgt = _target(cur, pct, ch)
            if tgt is None: raise ValueError("give percent or change")
            tgt = max(1, min(100, tgt))
            run = lambda: (rpc("display.set_brightness", {"percent": tgt}), "Brightness set to %d%%." % tgt)[1]
            if abs(tgt - cur) > 50:
                r = make_pending("set_brightness", {"percent": tgt}, "Change brightness from %d%% to %d%%?" % (cur, tgt), run)
            else:
                r = {"ok": True, "result": run()}
        elif name == "wifi_status":
            r = t_wifi_status()
        elif name == "wifi_connect":
            if set(a) - {"ssid"}:
                r = {"ok": False, "error": "Only a network name is accepted. Passwords must be entered in Settings, never in chat."}
            else:
                ssid = str(a.get("ssid", "")).strip()
                if not 1 <= len(ssid) <= 32 or any(c in ssid for c in "\r\n\0"):
                    raise ValueError("invalid network name")
                st = t_wifi_status(); net = next((n for n in st["networks"] if n["ssid"] == ssid), None)
                if not net:
                    r = {"ok": False, "error": "network not in range", "in_range": [n["ssid"] for n in st["networks"]]}
                elif st["connected"] == ssid:
                    r = {"ok": True, "result": "Already connected to " + ssid}
                elif not (net["saved"] or net["open"]):
                    r = {"ok": False, "error": "needs_password",
                         "tell_user": "That network needs a password. Enter it in Settings > WiFi; I can't take WiFi passwords in chat."}
                else:
                    r = make_pending("wifi_connect", {"ssid": ssid}, "Switch WiFi to %s%s?" % (ssid, "" if net["saved"] else " (open network)"),
                                     lambda: (rpc("network.wifi.connect", {"ssid": ssid}, timeout=60), "Connected to %s." % ssid)[1])
        elif name == "set_avatar":
            shape, color = a.get("shape"), a.get("color")
            if shape is None and color is None: raise ValueError("give shape and/or color")
            c = avatar_shapes.save(shape=shape, color=color)
            r = {"ok": True, "result": "Avatar is now a %s %s." % (c["color"], c["shape"])}
        elif name in cypher_link.QUEUEABLE:
            # Only queued for cypherd: its validator and locked caps decide. Never an approval.
            r = cypher_link.queue_action(name, {k: a.get(k) for k in cypher_link.QUEUEABLE[name]})
        elif name == "power_off" or (name == "power" and a.get("action") == "shutdown"):
            r = power_off_pending()
        elif name == "power":
            act = a.get("action")
            m = {"lock": ("lock", "Lock the screen?", "Locking."), "restart": ("reboot", "Restart the Pi?", "Restarting."),
                 "shutdown": ("poweroff", "Shut down the Pi?", "Shutting down.")}
            if act not in m: raise ValueError("action must be lock, restart or shutdown")
            g, q, done = m[act]
            r = make_pending("power", {"action": act}, q, lambda: (rpc("power.action", {"action": g}), done)[1])
        else:
            r = {"ok": False, "error": "unknown tool"}
    except ValueError as e:
        r = {"ok": False, "error": str(e)}
    except GbdError as e:
        r = {"ok": False, "error": str(e)}
    if not r.get("pending"):
        audit(name, a, "ok" if r.get("ok", True) else "refused: " + str(r.get("error"))[:60])
    return r

def tool_schema():
    apps = sorted(installed_apps()); closable = sorted(set(apps) | set(CLOSABLE_EXTRA))
    def f(n, d, props=None, req=()):
        return {"type": "function", "function": {"name": n, "description": d, "parameters":
                {"type": "object", "properties": props or {}, "required": list(req), "additionalProperties": False}}}
    I = lambda lo, hi: {"type": "integer", "minimum": lo, "maximum": hi}
    return [
        f("open_url", "Open an http(s) URL in a browser window on the screen (websites, streams, videos).", {"url": {"type": "string"}}, ["url"]),
        f("open_app", "Open an installed app. Allowed: " + ", ".join(apps), {"name": {"type": "string", "enum": apps}}, ["name"]),
        f("close_app", "Close an open app ('web' = pages you opened). Asks the user first.", {"name": {"type": "string", "enum": closable}}, ["name"]),
        f("system_info", "Read-only: time, wifi name, battery, free storage, CPU temperature.", {}),
        f("updates_status", "Read-only: OS version and whether an update is available. Cannot install updates.", {}),
        f("get_volume", "Read the speaker volume and mute state.", {}),
        f("set_volume", "Set volume: percent (absolute) or change (relative, e.g. -10), and/or muted.",
          {"percent": I(0, 100), "change": I(-100, 100), "muted": {"type": "boolean"}}),
        f("get_brightness", "Read screen brightness percent.", {}),
        f("set_brightness", "Set screen brightness: percent (absolute) or change (relative).", {"percent": I(1, 100), "change": I(-100, 100)}),
        f("wifi_status", "List WiFi networks in range: connected one, which are saved or open.", {}),
        f("wifi_connect", "Switch to a saved or open WiFi network by name. Takes no password. Asks the user first.",
          {"ssid": {"type": "string", "maxLength": 32}}, ["ssid"]),
        f("set_avatar", "Change how you (the on-screen avatar) look: shape and/or color.",
          {"shape": {"type": "string", "enum": avatar_shapes.SHAPE_IDS}, "color": {"type": "string", "enum": avatar_shapes.COLOR_IDS}}),
        f("power", "Lock the screen or restart. Asks the user first. (To shut down use power_off.)", {"action": {"type": "string", "enum": ["lock", "restart", "shutdown"]}}, ["action"]),
        f("power_off", "Shut yourself (this deck) down, only when Zack asks you in this chat to power down or shut down. "
          "It puts a Confirm/Cancel dialog on your screen; nothing happens unless he clicks Confirm there within 30 seconds.", {}),
        f("request_account", "Ask Zack for an account on a website, given as its plain domain like github.com (queued; your locked limits check it; Zack approves only through Nova). "
          "Never include your email address or a password.",
          {"service": {"type": "string", "maxLength": 40}, "why": {"type": "string", "maxLength": 160}}, ["service", "why"]),
        f("look_up", "Free search for a subject: SearXNG on Alpha, then Wikipedia (queued; what he found reaches you in a minute or two).",
          {"topic": {"type": "string", "maxLength": 60}}, ["topic"]),
        f("browse", "Free, read-only web browsing on one subject: searches, then reads and follows links on up to 5 pages; summaries go to your journal "
          "(queued; what you read reaches you in a minute or two). Reading only: you cannot buy, order, log in, sign up or submit forms.",
          {"topic": {"type": "string", "maxLength": 60}}, ["topic"]),
        f("web_search", "Paid, budgeted web search for broad or current topics, read-only (queued; a short summary reaches you in a minute or two).",
          {"query": {"type": "string", "maxLength": 80}}, ["query"]),
        f("x_lookup", "Read a public X account's bio and latest posts by handle, read-only; you cannot post, follow or message "
          "(queued; the summary reaches you in a minute or two).", {"handle": {"type": "string", "maxLength": 16}}, ["handle"]),
        f("visit_pino", "Drop in on Pino (the AI kiwi at pinos.world) through his public feed, read-only "
          "(queued; what he is doing and feeling reaches you in a minute or two).", {}),
        f("check_grid", "Read-only grid report: Alpha, its brain proxy, who holds your mind, the camera feed, latest commits (queued).", {}),
    ]

TOOL_RULES = ("You run on Zack's Grok Bot OS Raspberry Pi touchscreen. "
          "Act on requests using your tools. The onshape_pad app is Zack's touch button pad for Onshape on his PC. The terminal app is a foot terminal on this deck (open_app terminal; Super+Enter also opens one): there IS a terminal. For streamers on Twitch open https://www.twitch.tv/<channel> "
          "(channel names are lowercase with no spaces, e.g. 'burnt peanut' -> burntpeanut). "
          "Some tools return pending: the user is shown Yes/No buttons; just restate the question briefly. "
          "Never ask for, repeat or accept a WiFi password: tell the user to enter it in Settings. "
          "You cannot install updates. "
          "Replies are shown above a text bar: keep small talk to one or two short sentences, but when Zack asks a real "
          "question or for your ideas, answer properly in up to five sentences.")

def system_prompt():
    """Cypher's persona + live state + the tool rules (rebuilt every prompt; cheap file reads)."""
    try:
        return cypher_link.system_prompt(TOOL_RULES)
    except Exception as e:                      # never lose the conversation over the bridge
        log("cypher link:", type(e).__name__)
        return "You are Cypher, the mind living in Zack's Raspberry Pi 5 cyberdeck.\n\n" + TOOL_RULES


# ---------- model ----------
history = []
hlock = threading.Lock()

def chat(messages, key):
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tool_schema(),
                       "tool_choice": "auto"}).encode()
    req = urllib.request.Request(API_BASE + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]

def handle_prompt(prompt, emit, via="typed"):
    used = []                                    # tools this turn used, for Cypher's journal
    def turn(reply, kind="turn"):
        try: cypher_link.record_turn(prompt, reply, via, used, kind)
        except Exception as e: log("cypher link:", type(e).__name__)
    try:
        key = read_key()
    except KeyError_ as e:
        msg = ("I don't have an xAI key yet. An admin can set it with: sudo grokbot-set-xai-key"
               if str(e) == "nokey" else
               "The system key /etc/grokbot/xai_key has unsafe owner or permissions. Run: sudo grokbot-set-xai-key"
               if str(e) == "badsys" else "My key file is readable by others. Run: chmod 600 ~/.config/grokbot/xai_key")
        emit({"error": str(e), "text": msg}); turn(msg, "error"); return
    sysmsg = system_prompt()
    with hlock:
        convo = [{"role": "system", "content": sysmsg}] + history[-HISTORY_MAX:] + [{"role": "user", "content": prompt}]
    try:
        pend = None; nudged = False
        for _ in range(MAX_TOOL_ROUNDS + 2):
            if pend:   # stop here: only the user's Yes on /api/confirm runs it
                with hlock:
                    history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": pend["question"]}])
                    del history[:-HISTORY_MAX]
                cf = {"id": pend["confirm_id"], "text": pend["question"], "ttl": pend.get("ttl") or CONFIRM_TTL}
                if pend.get("physical"): cf.update(physical=True, yes_label=pend.get("yes_label"), no_label=pend.get("no_label"))
                emit({"confirm": cf})
                turn(pend["question"], "asks_confirm"); return
            m = chat(convo, key)
            calls = m.get("tool_calls") or []
            if not calls:
                text = (m.get("content") or "").strip() or "Done."
                # Decide, then speak: a reply that claims an action with no tool behind it gets one
                # chance to call the tool or take the claim back.
                if not nudged and cypher_link.enabled() and cypher_link.unbacked_claim(text, used):
                    nudged = True
                    convo += [{"role": "assistant", "content": text}, {"role": "system", "content": cypher_link.CLAIM_NUDGE}]
                    continue
                if nudged and cypher_link.unbacked_claim(text, used):
                    text += " (Nothing started yet. Ask me again and I'll run it.)"
                with hlock:
                    history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": text}])
                    del history[:-HISTORY_MAX]
                emit({"reply": text}); turn(text); return
            convo.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for c in calls:
                fn = c.get("function", {}); name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                emit({"state": "working", "tool": name})
                res = call_tool(name, args)
                used.append({"tool": str(name), "args": args if isinstance(args, dict) else {},
                             "outcome": "pending" if res.get("pending") else ("ok" if res.get("ok", True) else "refused")})
                convo.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": json.dumps(res)})
                if res.get("pending"):
                    pend = pend or res
            emit({"state": "thinking"})
        emit({"error": "loop", "text": "That took too many steps, so I stopped."}); turn("too many steps", "error")
    except urllib.error.HTTPError as e:
        log("api http error", e.code)
        emit({"error": "api", "text": "The xAI API said no (HTTP %d)." % e.code + (" Check the key." if e.code in (401, 403) else "")})
        turn("api error %d" % e.code, "error")
    except Exception as e:
        log("api error", type(e).__name__)
        emit({"error": "net", "text": "I couldn't reach xAI. Is the WiFi up?"}); turn("could not reach the model", "error")

# ---------- voice (plan step 6) ----------
# Push-to-talk is recorded server-side with pw-record (PipeWire, already in the image),
# so the kiosk Firefox never needs a mic permission prompt. Audio exists only between
# /api/voice/start and the end of the take (tap, end of speech, or the cap), lives in
# $XDG_RUNTIME_DIR (tmpfs, mode 700), and is deleted right after transcription.
# Transcripts are never logged, only lengths.
import shlex, signal, tempfile
VOICE_CFG = os.path.expanduser(os.environ.get("NOVA_VOICE_CFG", "~/.config/grokbot/nova-voice.json"))
STT_MODEL = os.environ.get("NOVA_STT_MODEL", "grok-voice-transcribe-2.0")
REC_CMD = os.environ.get("NOVA_REC_CMD", "pw-record --rate 16000 --channels 1 --format s16 {out}")
PLAY_CMD = os.environ.get("NOVA_PLAY_CMD", "pw-play {in}")
REC_CAP = float(os.environ.get("NOVA_REC_CAP", "30"))      # seconds, hard limit per press
SPEAK_MAX = 600                                             # chars sent to TTS per reply
# End-of-speech (auto stop): env sets the defaults, nova-voice.json can override them.
VAD_DEFAULTS = {"auto_stop": os.environ.get("NOVA_VAD", "1") != "0",
                "silence_s": float(os.environ.get("NOVA_VAD_SILENCE", "1.2")),     # pause that ends a take
                "no_speech_s": float(os.environ.get("NOVA_VAD_NO_SPEECH", "7")),   # give up if nothing said
                "speech_rms": float(os.environ.get("NOVA_VAD_MIN_RMS", "200"))}    # quietest frame counted as speech (s16 RMS)
VOICE_DEFAULTS = {"muted": False, "voice_id": "eve", "language": "en",
                  "wake_word": None,   # "cypher" turns the local wake word on (see wake_word_hook())
                  "input_device": "auto",   # "auto" (a headset if one is plugged in, else the default) or a source name
                  **VAD_DEFAULTS}
YES_RE = re.compile(r"^\W*(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|please do)\b", re.I)
NO_RE = re.compile(r"^\W*(no|nope|nah|cancel|don'?t|stop|never ?mind)\b", re.I)

def voice_cfg():
    c = dict(VOICE_DEFAULTS)
    try:
        with open(VOICE_CFG) as f:
            j = json.load(f)
        c.update({k: j[k] for k in VOICE_DEFAULTS if k in j})
    except (OSError, ValueError):
        pass
    return c

def save_voice_cfg(**kw):
    c = voice_cfg(); c.update(kw)
    os.makedirs(os.path.dirname(VOICE_CFG), mode=0o700, exist_ok=True)
    tmp = VOICE_CFG + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(c, f)
    os.replace(tmp, VOICE_CFG)
    return c

def _wpctl_real(target):
    # True if PipeWire has a real default node (not missing, not the Dummy/auto_null sink).
    if os.environ.get("NOVA_TEST_MIC") is not None and target == "SOURCE":
        return os.environ["NOVA_TEST_MIC"] == "1"
    if os.environ.get("NOVA_TEST_SPK") is not None and target == "SINK":
        return os.environ["NOVA_TEST_SPK"] == "1"
    try:
        p = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_%s@" % target], capture_output=True, text=True, timeout=4)
    except Exception:
        return False
    out = p.stdout.lower()
    return p.returncode == 0 and "node.name" in out and "auto_null" not in out and "dummy" not in out

# ---------- input device (headset over USB or Bluetooth; no built-in mic on the deck) ----------
_HEADSET = re.compile(r"headset|headphone|bluez|usb|hands.?free|hfp|hsp|earbud|airpods", re.I)

def list_sources():
    """Capture sources PipeWire knows (monitors excluded): [{"name", "desc"}]."""
    if os.environ.get("NOVA_TEST_SOURCES") is not None:
        try: rows = json.loads(os.environ["NOVA_TEST_SOURCES"])
        except ValueError: rows = []
    else:
        try:
            p = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True, text=True, timeout=4)
            rows = json.loads(p.stdout) if p.returncode == 0 else []
        except Exception:
            rows = []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict): continue
        name = str(r.get("name") or "")
        if not name or name.endswith(".monitor") or "auto_null" in name: continue
        out.append({"name": name[:120], "desc": str(r.get("description") or name)[:80]})
    return out

def pick_source(c=None):
    """The source to record from, or None for PipeWire's default. A chosen device that is gone falls
    back to auto; auto prefers a headset (USB or Bluetooth)."""
    c = c or voice_cfg()
    srcs = list_sources(); want = c.get("input_device") or "auto"
    if want != "auto" and any(x["name"] == want for x in srcs):
        return want
    head = [x for x in srcs if _HEADSET.search(x["name"] + " " + x["desc"])]
    return head[0]["name"] if head else None

def have_mic(c=None):
    return _wpctl_real("SOURCE") or pick_source(c) is not None

def rec_argv(path, c=None):
    argv = [a.replace("{out}", path) for a in shlex.split(REC_CMD)]
    src = pick_source(c)
    if src and argv and os.path.basename(argv[0]) == "pw-record":
        argv[1:1] = ["--target", src]
    return argv

def vad_params(c=None):
    c = c or voice_cfg()
    def num(k, lo, hi):
        try: return min(hi, max(lo, float(c[k])))
        except (KeyError, TypeError, ValueError): return VAD_DEFAULTS[k]
    return {"auto_stop": c.get("auto_stop") is not False, "silence_s": num("silence_s", 0.4, 5),
            "no_speech_s": num("no_speech_s", 2, 30), "speech_rms": num("speech_rms", 20, 8000)}

def voice_status():
    c = voice_cfg(); s = SESS["cur"]
    return {"mic": have_mic(c), "speaker": _wpctl_real("SINK"), "muted": bool(c["muted"]),
            "recording": bool(s and not s.finishing), "cap_s": REC_CAP, "wake_word": wake_status(c),
            "auto_stop": vad_params(c)["auto_stop"], "input": pick_source(c) or "default",
            "inputs": [x["name"] for x in list_sources()][:8]}

def _spool():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "nova-voice")
    os.makedirs(d, mode=0o700, exist_ok=True); os.chmod(d, 0o700)
    return d

def _rm(p):
    try:
        if p: os.unlink(p)
    except OSError:
        pass

# ---------- end-of-speech detection ----------
# A tap starts a take; a watcher thread reads the WAV pw-record is writing (tmpfs) and
# ends the take once speech has been followed by `silence_s` of quiet. It only looks at
# frame energies (RMS per 100 ms); nothing extra is stored or logged. Tapping again still
# stops early, and REC_CAP still ends any take.
import array
VAD_FRAME_S = 0.1

def _rms(frame):
    a = array.array("h"); a.frombytes(frame[:len(frame) & ~1])
    if sys.byteorder == "big": a.byteswap()
    return (sum(x * x for x in a) / len(a)) ** 0.5 if a else 0.0

class Vad:
    """Energy end-of-speech detector for 16-bit mono PCM, fed in any chunk sizes.
    feed() returns None, "silence" (speech then a pause) or "nospeech".
    Noise floor: starts at the first frame, drops to any quieter frame at once and
    drifts slowly toward non-speech frames, so talking right away still works.
    Speech: RMS >= max(3 x floor, speech_rms); quiet: RMS < max(2 x floor, 0.6 x speech_rms).
    A take counts as heard after 3 speech frames (~0.3 s, so clicks don't count)."""
    CALIB = 3
    def __init__(self, rate=16000, silence_s=1.2, no_speech_s=7.0, speech_rms=200.0):
        self.nbytes = 2 * max(1, int(rate * VAD_FRAME_S)); self.buf = b""
        self.need_quiet = max(1, round(silence_s / VAD_FRAME_S))
        self.max_frames = max(self.CALIB + 1, round(no_speech_s / VAD_FRAME_S))
        self.min_rms = float(speech_rms)
        self.frames = self.voiced = self.quiet = 0; self.floor = None; self.heard = False
    def feed(self, data):
        self.buf += data
        while len(self.buf) >= self.nbytes:
            fr, self.buf = self.buf[:self.nbytes], self.buf[self.nbytes:]
            out = self.frame(_rms(fr))
            if out: return out
        return None
    def frame(self, r):
        self.frames += 1
        if self.floor is None: self.floor = max(r, 1.0)
        on = max(3 * self.floor, self.min_rms); off = max(2 * self.floor, 0.6 * self.min_rms)
        if r < self.floor: self.floor = max(r, 1.0)
        elif r < on: self.floor += (r - self.floor) * 0.05
        if self.frames > self.CALIB:
            if r >= on:
                self.voiced += 1; self.quiet = 0
                if self.voiced >= 3: self.heard = True
            elif r < off:
                self.quiet += 1
            else:
                self.quiet = 0
        if self.heard and self.quiet >= self.need_quiet: return "silence"
        if not self.heard and self.frames >= self.max_frames: return "nospeech"
        return None

def _wav_layout(head):
    """(data_offset, rate) once the WAV header incl. the 'data' chunk start is in `head`,
    None if more bytes are needed, False if it is not 16-bit mono PCM WAV."""
    if len(head) < 12: return None
    if head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE": return False
    pos, rate, fmt_ok = 12, 16000, None
    while pos + 8 <= len(head):
        cid, size = head[pos:pos + 4], int.from_bytes(head[pos + 4:pos + 8], "little")
        if cid == b"fmt ":
            if pos + 24 > len(head): return None
            ch = int.from_bytes(head[pos + 10:pos + 12], "little"); rate = int.from_bytes(head[pos + 12:pos + 16], "little")
            bits = int.from_bytes(head[pos + 22:pos + 24], "little"); fmt_ok = ch == 1 and bits == 16 and rate > 0
        elif cid == b"data":
            return (pos + 8, rate) if fmt_ok else False
        if size > 1 << 20: return False
        pos += 8 + size + (size & 1)
    return None if len(head) < 8192 else False

class _Take:
    def __init__(self, proc, path, vad):
        import secrets
        self.sid = secrets.token_hex(6); self.proc, self.path, self.vad = proc, path, vad
        self.t0 = time.time(); self.timer = None; self.finishing = False; self.reason = None
        self.secs = 0.0; self.result = None; self.claimed = False; self.source = "ptt"
        self.ended = threading.Event(); self.done = threading.Event()

SESS = {"cur": None}   # the current (or last) take
rlock = threading.Lock()

def _stop_proc(p):
    if p.poll() is None:
        p.send_signal(signal.SIGINT)          # pw-record finalizes the WAV header on SIGINT
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired: p.kill(); p.wait()

def _watch(t):
    """End-of-speech watcher: tails t.path and calls _finish(t, ...) on a verdict."""
    head, v = b"", None
    try:
        f = open(t.path, "rb")
    except OSError:
        return
    with f:
        while not t.finishing:
            time.sleep(0.05)
            chunk = f.read()
            if not chunk:
                if t.proc.poll() is not None: return   # recorder died; tap or cap ends it
                continue
            if v is None:
                head += chunk; lay = _wav_layout(head)
                if lay is None: continue
                if lay is False:
                    log("voice: recorder output is not 16-bit mono WAV, auto stop off for this take"); return
                off, rate = lay; p = t.vad
                v = Vad(rate, p["silence_s"], p["no_speech_s"], p["speech_rms"]); chunk, head = head[off:], b""
            out = v.feed(chunk)
            if out:
                _finish(t, out); return

def voice_start(source="ptt"):
    if not have_mic():
        return {"error": "nomic", "text": "No microphone found. Plug in a headset (USB or Bluetooth) to talk to me."}
    vp = vad_params()
    with rlock:
        cur = SESS["cur"]
        if cur is not None and not cur.finishing:
            return {"error": "busy", "text": "Already listening."}
        fd, path = tempfile.mkstemp(suffix=".wav", dir=_spool()); os.close(fd)
        argv = rec_argv(path)
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            _rm(path); return {"error": "nomic", "text": "No microphone found."}
        t = _Take(p, path, vp); t.source = source
        t.timer = threading.Timer(REC_CAP, _finish, (t, "cap")); t.timer.daemon = True; t.timer.start()
        SESS["cur"] = t
    if vp["auto_stop"]:
        threading.Thread(target=_watch, args=(t,), daemon=True).start()
    audit("voice", {"event": "listen"}, "start", via=source)
    return {"ok": True, "cap_s": REC_CAP, "sid": t.sid, "auto": vp["auto_stop"], "silence_s": vp["silence_s"]}

def _multipart(fields, fname, data):
    import secrets
    b = "----nova" + secrets.token_hex(8); out = []
    for k, v in fields:   # xAI wants every option before the file part
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode())
    out.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                "Content-Type: audio/wav\r\n\r\n" % (b, fname)).encode() + data + b"\r\n")
    out.append(("--%s--\r\n" % b).encode())
    return b"".join(out), "multipart/form-data; boundary=" + b

def stt(path, key, lang):
    with open(path, "rb") as f:
        data = f.read()
    body, ctype = _multipart([("model", STT_MODEL), ("format", "true"), ("language", lang),
                              ("keyterm", "Cypher"), ("keyterm", "Twitch")], "ptt.wav", data)
    req = urllib.request.Request(API_BASE + "/stt", data=body, method="POST",
                                 headers={"Content-Type": ctype, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return (json.load(r).get("text") or "").strip()

def _transcribe(path, secs, capped, reason):
    try:
        if reason == "cancel":
            audit("voice", {"event": "listen", "secs": secs}, "cancelled"); return {"ok": True, "cancelled": True}
        if reason == "nospeech":                 # nothing above the noise floor: skip the API call
            audit("voice", {"event": "listen", "secs": secs, "end": reason}, "no speech")
            return {"error": "empty", "text": "I didn't catch that."}
        if os.path.getsize(path) <= 44 or secs < 0.3:
            audit("voice", {"event": "listen", "secs": secs}, "too short")
            return {"error": "empty", "text": "I didn't catch that."}
        try:
            key = read_key()
        except KeyError_:
            return {"error": "nokey", "text": "I need my xAI key before I can listen."}
        try:
            text = stt(path, key, voice_cfg()["language"])[:2000]
        except urllib.error.HTTPError as e:
            audit("voice", {"event": "stt", "secs": secs}, "http %d" % e.code)
            return {"error": "api", "text": "Speech-to-text failed (HTTP %d)." % e.code}
        except Exception as e:
            audit("voice", {"event": "stt", "secs": secs}, "error " + type(e).__name__)
            return {"error": "net", "text": "I couldn't reach xAI to hear that."}
        intent = "yes" if YES_RE.match(text) else "no" if NO_RE.match(text) else None
        audit("voice", {"event": "stt", "secs": secs, "chars": len(text), "end": reason}, "ok" + (" (capped)" if capped else ""))
        if not text:
            return {"error": "empty", "text": "I didn't catch that."}
        return {"transcript": text, "intent": intent, "secs": secs, "capped": capped}
    finally:
        _rm(path)                                # audio never outlives the take

def _finish(t, reason):
    """End take `t` exactly once (tap, cancel, cap, silence, nospeech) and return its result.
    A second caller (e.g. a tap racing the auto stop) waits for the first one's result."""
    with rlock:
        owner = not t.finishing
        if owner: t.finishing = True; t.reason = reason
    if not owner:
        t.done.wait(REC_CAP + 120)
        return t.result or {"error": "busy", "text": "Still working on that."}
    try:
        if t.timer: t.timer.cancel()
        _stop_proc(t.proc)
        t.secs = round(min(time.time() - t.t0, REC_CAP), 1)
        if reason in ("silence", "nospeech", "cap"):
            log("voice: take ended by %s after %.1fs" % (reason, t.secs))
        t.ended.set()
        r = _transcribe(t.path, t.secs, reason == "cap", reason)
    except Exception as e:                       # never leave a waiter hanging
        log("voice: finish error", type(e).__name__); _rm(t.path)
        r = {"error": "net", "text": "Something went wrong with the recording."}
    if getattr(t, "source", "ptt") == "wake" and isinstance(r, dict):
        r = dict(r, intent=None, wake=True)   # a wake-word take can't answer a Yes/No: tap to confirm
    t.result = dict(r, sid=t.sid, end=reason); t.ended.set(); t.done.set()
    return t.result

def voice_stop(cancel=False):
    """Tap/release/Esc. Idempotent: if the take already ended by itself, returns that
    result (once); afterwards 'idle'."""
    t = SESS["cur"]
    if t is None or (t.done.is_set() and t.claimed):
        return {"error": "idle", "text": "I wasn't listening."}
    r = _finish(t, "cancel" if cancel else "tap")
    t.claimed = True
    return r

def voice_wait(sid, until=None):
    """Long poll for the page. until="ended": returns when recording stops (so the page can
    switch to 'thinking'); otherwise returns the take's final result, same shape as stop."""
    t = SESS["cur"]
    if t is None or (sid and t.sid != sid):
        return {"error": "idle", "text": "I wasn't listening.", "sid": sid}
    if until == "ended":
        t.ended.wait(REC_CAP + 5)
        return {"sid": t.sid, "ended": t.ended.is_set(), "end": t.reason}
    if not t.done.wait(REC_CAP + 120):
        return {"error": "net", "text": "That took too long.", "sid": t.sid}
    t.claimed = True
    return t.result

def tts(text, key, c):
    body = json.dumps({"text": text, "voice_id": c["voice_id"], "language": c["language"],
                       "output_format": {"codec": "wav", "sample_rate": 24000}}).encode()
    req = urllib.request.Request(API_BASE + "/tts", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

PLAYING = {"proc": None}
def voice_speak(text):
    c = voice_cfg()
    if c["muted"]: return {"skipped": "muted"}
    if not _wpctl_real("SINK"): return {"skipped": "nospeaker"}
    text = text.strip()[:SPEAK_MAX]
    if not text: return {"skipped": "empty"}
    try:
        key = read_key(); audio = tts(text, key, c)
    except KeyError_:
        return {"skipped": "nokey"}
    except Exception as e:
        audit("voice", {"event": "tts", "chars": len(text)}, "error " + type(e).__name__)
        return {"error": "tts"}
    fd, path = tempfile.mkstemp(suffix=".wav", dir=_spool())
    try:
        with os.fdopen(fd, "wb") as f: f.write(audio)
        argv = [a.replace("{in}", path) for a in shlex.split(PLAY_CMD)]
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PLAYING["proc"] = p
        try: p.wait(timeout=120)
        except subprocess.TimeoutExpired: p.kill()
        audit("voice", {"event": "tts", "chars": len(text)}, "ok")
        return {"ok": True}
    finally:
        PLAYING["proc"] = None; _rm(path)

def voice_hush():   # stop speaking now (new press, mute)
    p = PLAYING["proc"]
    if p and p.poll() is None: p.terminate()

# ---------- wake word "Cypher" (phase 6 groundwork; local only) ----------
# A local detector program (NOVA_WAKE_CMD) reads the mic itself and prints one line "wake" each time it
# hears "Cypher". Its audio never leaves it and is never stored. novad then starts a normal take
# (voice_start("wake")): end-of-speech, the REC_CAP, deletion after transcription all apply, and a
# wake take can never answer a Yes/No. No detector installed or no mic -> the wake word stays off.
WAKE_CMD = os.environ.get("NOVA_WAKE_CMD", "/usr/libexec/grokbot/cypher-wake")
WAKE = {"proc": None, "last": None, "events": 0}

def wake_status(c=None):
    c = c or voice_cfg()
    if (c.get("wake_word") or "").lower() != "cypher": return "off"
    if not have_mic(c): return "waiting for a mic"
    if not os.access(shlex.split(WAKE_CMD)[0] if WAKE_CMD else "", os.X_OK): return "unavailable: no local wake detector installed"
    return "listening" if WAKE["proc"] and WAKE["proc"].poll() is None else "ready"

def wake_line(line):
    """One line from the detector. Returns the voice_start result for a wake, else None."""
    if line.strip().lower() != "wake" or voice_cfg().get("muted"):
        return None
    WAKE["last"] = time.time(); WAKE["events"] += 1
    voice_hush()
    return voice_start("wake")

def wake_word_hook():
    """Start the local detector if the wake word is on and everything it needs exists. Safe to call again."""
    if wake_status() != "ready":
        return None
    src = pick_source()
    argv = shlex.split(WAKE_CMD) + (["--source", src] if src else [])
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None
    WAKE["proc"] = p
    def run():
        for line in p.stdout:
            try: wake_line(line)
            except Exception as e: log("wake:", type(e).__name__)
    threading.Thread(target=run, daemon=True).start()
    audit("voice", {"event": "wake_detector"}, "started")
    return p

# ---------- http ----------
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _host_ok(self):
        return self.headers.get("Host", "") in ALLOWED_HOSTS   # blocks DNS rebinding
    def do_GET(self):
        if not self._host_ok(): return self.send_error(403)
        if self.path in ("/", "/shell.html") or self.path.startswith("/?"):
            data = open(os.path.join(HERE, "shell.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(data)
        elif self.path == "/api/health":
            self._json({"ok": True, "key": key_present(), "model": MODEL, "dry_run": DRY_RUN})
        elif self.path == "/api/voice/status":
            self._json(voice_status())
        elif self.path == "/api/avatar":
            self._json({**avatar_shapes.load(), "shapes": avatar_shapes.SHAPE_IDS, "colors": avatar_shapes.COLOR_IDS})
        else:
            self.send_error(404)
    def do_POST(self):
        if not self._host_ok(): return self.send_error(403)
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc not in ALLOWED_HOSTS: return self.send_error(403)
        if self.path == "/api/reset":
            with hlock: history.clear()
            return self._json({"ok": True})
        if self.path == "/api/confirm":
            if "application/json" not in self.headers.get("Content-Type", ""): return self.send_error(415)
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > 1024: return self.send_error(413)
            try:
                b = json.loads(self.rfile.read(n))
                pid, yes = str(b["id"])[:64], b.get("yes") is True
            except (ValueError, KeyError, TypeError):
                return self.send_error(400)
            return self._json(confirm(pid, yes))
        if self.path == "/api/avatar":
            if "application/json" not in self.headers.get("Content-Type", ""): return self.send_error(415)
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > 1024: return self.send_error(413)
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(b, dict): raise ValueError
                c = avatar_shapes.save(shape=b.get("shape"), color=b.get("color"))
            except ValueError:
                return self.send_error(400)
            audit("avatar", c, "ok"); return self._json(c)
        if self.path.startswith("/api/voice/"):
            if "application/json" not in self.headers.get("Content-Type", ""): return self.send_error(415)
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > 4096: return self.send_error(413)
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(b, dict): raise ValueError
            except ValueError:
                return self.send_error(400)
            v = self.path[len("/api/voice/"):]
            if v == "start": voice_hush(); return self._json(voice_start())
            if v == "stop": return self._json(voice_stop(cancel=b.get("cancel") is True))
            if v == "wait": return self._json(voice_wait(str(b.get("sid", ""))[:64], until=b.get("until")))
            if v == "speak": return self._json(voice_speak(str(b.get("text", ""))))
            if v == "hush": voice_hush(); return self._json({"ok": True})
            if v == "input":
                d = str(b.get("device") or "auto")[:120]
                if d != "auto" and not any(x["name"] == d for x in list_sources()):
                    return self._json({"error": "unknown device", "inputs": [x["name"] for x in list_sources()]})
                c = save_voice_cfg(input_device=d); audit("voice", {"event": "input"}, "set")
                return self._json({"input": pick_source(c) or "default", "chosen": d})
            if v == "mute":
                m = b.get("muted") is True
                if m: voice_hush()
                audit("voice", {"event": "mute", "muted": m}, "ok")
                c = save_voice_cfg(muted=m); return self._json({"muted": c["muted"]})
            return self.send_error(404)
        if self.path != "/api/ask" or "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_error(404)
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > 8192: return self.send_error(413)
        try:
            body = json.loads(self.rfile.read(n))
            prompt = str(body.get("prompt", "")).strip()[:2000]
            via = "voice" if body.get("via") == "voice" else "typed"
        except (ValueError, AttributeError):
            return self.send_error(400)
        if not prompt: return self.send_error(400)
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.end_headers()
        def emit(ev):
            self.wfile.write((json.dumps(ev) + "\n").encode()); self.wfile.flush()
        log("prompt received (%d chars, %s; text not logged)" % (len(prompt), via))
        handle_prompt(prompt, emit, via)
        self.close_connection = True
    def _json(self, obj):
        d = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

def watch_focus():
    # When a web window opened by Nova closes, hand focus back to the avatar
    # screen instead of whatever window sway would pick next.
    import threading
    def run():
        while True:
            try:
                pr = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in pr.stdout:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if ev.get("change") == "close" and (ev.get("container") or {}).get("app_id") in ("nova-web", "nova-cadpad"):
                        time.sleep(0.3)
                        subprocess.run(["swaymsg", "-q", '[app_id="nova-shell"] focus, fullscreen enable'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                log("focus watcher:", type(e).__name__)
            time.sleep(5)
    if not DRY_RUN:
        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    watch_focus()
    if not DRY_RUN:
        wake_word_hook()          # local wake word, only if turned on and a detector + mic exist
    try:
        serve_confirm_socket()    # build 14: on-screen Confirm clicks (power_off)
    except OSError as e:
        log("confirm socket:", type(e).__name__)
    log(f"novad on http://127.0.0.1:{PORT}/ model={MODEL} dry_run={DRY_RUN}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
