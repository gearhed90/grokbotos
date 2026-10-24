#!/usr/bin/env python3
"""novad - Nova prompt-shell backend for grokbotos (stdlib only).

Serves shell.html on http://127.0.0.1:PORT/ and handles prompts via the xAI
chat completions API with a small allowlisted toolset. No shell-exec tool.
Key: /etc/grokbot/xai_key (root-owned, group grokbot, mode 0640; set with
sudo grokbot-set-xai-key), else ~/.config/grokbot/xai_key (mode 600). Never logged.
"""
import json, os, re, shutil, stat, subprocess, sys, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

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
    safe = {k: v for k, v in (args or {}).items() if k in ("ssid", "name", "action", "percent", "change", "muted", "event", "secs", "chars")}
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
    apps.pop("nova-shell", None)
    return apps

CLOSABLE_EXTRA = {"web": "nova-web"}   # pages Nova opened with open_url

def t_open_app(name):
    apps = installed_apps(); n = str(name).strip().lower()
    if n not in apps:
        return {"ok": False, "error": "app not allowed", "allowed": sorted(apps)}
    launch(["firefox", "--new-window"] if n == "firefox" else ["/usr/local/bin/grokbot-webapp", n])
    return {"ok": True, "opened": n}

def close_target(name):
    n = str(name).strip().lower()
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
            "note": "Nova only reads update status; installing updates is done in Settings."}

# ---------- confirmations ----------
PENDING = {}; plock = threading.Lock(); CONFIRM_TTL = int(os.environ.get("NOVA_CONFIRM_TTL", "60"))

def make_pending(tool, args, text, run):
    import secrets
    pid = secrets.token_urlsafe(12)
    with plock:
        now = time.time()
        for k in [k for k, v in PENDING.items() if v["exp"] < now]: del PENDING[k]
        PENDING[pid] = {"tool": tool, "args": args, "text": text, "run": run, "exp": now + CONFIRM_TTL}
    audit(tool, args, "pending")
    return {"ok": False, "pending": True, "confirm_id": pid, "question": text}

def confirm(pid, yes):
    with plock:
        p = PENDING.pop(str(pid), None)   # single use
    if not p:
        return {"error": "gone", "text": "That request expired or was already answered."}
    if p["exp"] < time.time():
        audit(p["tool"], p["args"], "expired")
        return {"error": "expired", "text": "That request expired. Ask me again."}
    if not yes:
        audit(p["tool"], p["args"], "declined")
        return {"reply": "Okay, I won't."}
    try:
        res = p["run"]()
        audit(p["tool"], p["args"], "ok", via="confirmed")
        return {"reply": res}
    except (GbdError, subprocess.SubprocessError, OSError) as e:
        audit(p["tool"], p["args"], "error: " + str(e)[:80], via="confirmed")
        return {"error": "action", "text": "That didn't work: " + str(e)[:120]}

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
        f("power", "Lock the screen, restart or shut down. Asks the user first.", {"action": {"type": "string", "enum": ["lock", "restart", "shutdown"]}}, ["action"]),
    ]

SYSTEM = ("You are Nova, the assistant built into Zack's Grok Bot OS on a Raspberry Pi touchscreen. "
          "Act on requests using your tools. For streamers on Twitch open https://www.twitch.tv/<channel> "
          "(channel names are lowercase with no spaces, e.g. 'burnt peanut' -> burntpeanut). "
          "Some tools return pending: the user is shown Yes/No buttons; just restate the question briefly. "
          "Never ask for, repeat or accept a WiFi password: tell the user to enter it in Settings. "
          "You cannot install updates. "
          "Replies are shown in one line above a text bar: keep them to one or two short sentences.")

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

def handle_prompt(prompt, emit):
    try:
        key = read_key()
    except KeyError_ as e:
        msg = ("I don't have an xAI key yet. An admin can set it with: sudo grokbot-set-xai-key"
               if str(e) == "nokey" else
               "The system key /etc/grokbot/xai_key has unsafe owner or permissions. Run: sudo grokbot-set-xai-key"
               if str(e) == "badsys" else "My key file is readable by others. Run: chmod 600 ~/.config/grokbot/xai_key")
        emit({"error": str(e), "text": msg}); return
    with hlock:
        convo = [{"role": "system", "content": SYSTEM}] + history[-HISTORY_MAX:] + [{"role": "user", "content": prompt}]
    try:
        pend = None
        for _ in range(MAX_TOOL_ROUNDS + 1):
            if pend:   # stop here: only the user's Yes on /api/confirm runs it
                with hlock:
                    history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": pend["question"]}])
                    del history[:-HISTORY_MAX]
                emit({"confirm": {"id": pend["confirm_id"], "text": pend["question"], "ttl": CONFIRM_TTL}}); return
            m = chat(convo, key)
            calls = m.get("tool_calls") or []
            if not calls:
                text = (m.get("content") or "").strip() or "Done."
                with hlock:
                    history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": text}])
                    del history[:-HISTORY_MAX]
                emit({"reply": text}); return
            convo.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for c in calls:
                fn = c.get("function", {}); name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                emit({"state": "working", "tool": name})
                res = call_tool(name, args)
                convo.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": json.dumps(res)})
                if res.get("pending"):
                    pend = pend or res
            emit({"state": "thinking"})
        emit({"error": "loop", "text": "That took too many steps, so I stopped."})
    except urllib.error.HTTPError as e:
        log("api http error", e.code)
        emit({"error": "api", "text": "The xAI API said no (HTTP %d)." % e.code + (" Check the key." if e.code in (401, 403) else "")})
    except Exception as e:
        log("api error", type(e).__name__)
        emit({"error": "net", "text": "I couldn't reach xAI. Is the WiFi up?"})

# ---------- voice (plan step 6) ----------
# Push-to-talk is recorded server-side with pw-record (PipeWire, already in the image),
# so the kiosk Firefox never needs a mic permission prompt. Audio exists only between
# /api/voice/start and /api/voice/stop, lives in $XDG_RUNTIME_DIR (tmpfs, mode 700),
# and is deleted right after transcription. Transcripts are never logged, only lengths.
import shlex, signal, tempfile
VOICE_CFG = os.path.expanduser(os.environ.get("NOVA_VOICE_CFG", "~/.config/grokbot/nova-voice.json"))
STT_MODEL = os.environ.get("NOVA_STT_MODEL", "grok-voice-transcribe-2.0")
REC_CMD = os.environ.get("NOVA_REC_CMD", "pw-record --rate 16000 --channels 1 --format s16 {out}")
PLAY_CMD = os.environ.get("NOVA_PLAY_CMD", "pw-play {in}")
REC_CAP = float(os.environ.get("NOVA_REC_CAP", "30"))      # seconds, hard limit per press
SPEAK_MAX = 600                                             # chars sent to TTS per reply
VOICE_DEFAULTS = {"muted": False, "voice_id": "eve", "language": "en",
                  "wake_word": None}   # wake_word: reserved hook, see wake_word_hook()
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

def voice_status():
    c = voice_cfg()
    return {"mic": _wpctl_real("SOURCE"), "speaker": _wpctl_real("SINK"), "muted": bool(c["muted"]),
            "recording": REC["proc"] is not None, "cap_s": REC_CAP, "wake_word": None}

def _spool():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "nova-voice")
    os.makedirs(d, mode=0o700, exist_ok=True); os.chmod(d, 0o700)
    return d

def _rm(p):
    try:
        if p: os.unlink(p)
    except OSError:
        pass

REC = {"proc": None, "path": None, "t0": 0, "timer": None, "capped": False}
rlock = threading.Lock()

def _stop_proc(p):
    if p.poll() is None:
        p.send_signal(signal.SIGINT)          # pw-record finalizes the WAV header on SIGINT
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired: p.kill(); p.wait()

def _cap_hit():
    with rlock:
        if REC["proc"] is not None:
            REC["capped"] = True
            _stop_proc(REC["proc"])
            log("voice: %.0fs cap reached, recording stopped" % REC_CAP)

def voice_start(source="ptt"):
    if not _wpctl_real("SOURCE"):
        return {"error": "nomic", "text": "No microphone found."}
    with rlock:
        if REC["proc"] is not None:
            return {"error": "busy", "text": "Already listening."}
        fd, path = tempfile.mkstemp(suffix=".wav", dir=_spool()); os.close(fd)
        argv = [a.replace("{out}", path) for a in shlex.split(REC_CMD)]
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            _rm(path); return {"error": "nomic", "text": "No microphone found."}
        t = threading.Timer(REC_CAP, _cap_hit); t.daemon = True; t.start()
        REC.update(proc=p, path=path, t0=time.time(), timer=t, capped=False)
    audit("voice", {"event": "listen"}, "start", via=source)
    return {"ok": True, "cap_s": REC_CAP}

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
                              ("keyterm", "Nova"), ("keyterm", "Twitch")], "ptt.wav", data)
    req = urllib.request.Request(API_BASE + "/stt", data=body, method="POST",
                                 headers={"Content-Type": ctype, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return (json.load(r).get("text") or "").strip()

def voice_stop(cancel=False):
    with rlock:
        p, path, t0, capped = REC["proc"], REC["path"], REC["t0"], REC["capped"]
        if p is None:
            return {"error": "idle", "text": "I wasn't listening."}
        REC["timer"].cancel(); _stop_proc(p)
        REC.update(proc=None, path=None, timer=None)
    secs = round(min(time.time() - t0, REC_CAP), 1)
    try:
        if cancel:
            audit("voice", {"event": "listen", "secs": secs}, "cancelled"); return {"ok": True, "cancelled": True}
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
        audit("voice", {"event": "stt", "secs": secs, "chars": len(text)}, "ok" + (" (capped)" if capped else ""))
        if not text:
            return {"error": "empty", "text": "I didn't catch that."}
        return {"transcript": text, "intent": intent, "secs": secs, "capped": capped}
    finally:
        _rm(path)                                # audio never outlives the request

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

def wake_word_hook():
    """Reserved for a later wake word ("Nova"). Not implemented on purpose.
    A future detector (always-on, local-only, e.g. a small keyword model reading a
    pw-record stream that is never stored or sent) should call voice_start("wake")
    and signal the page through a GET /api/voice/events stream so it can show
    'listening' and later call /api/voice/stop on silence (xAI streaming STT's
    speech_final). Enabled only when nova-voice.json has "wake_word": "nova"."""
    return None

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
            if v == "speak": return self._json(voice_speak(str(b.get("text", ""))))
            if v == "hush": voice_hush(); return self._json({"ok": True})
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
        handle_prompt(prompt, emit)
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
                    if ev.get("change") == "close" and (ev.get("container") or {}).get("app_id") == "nova-web":
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
    log(f"novad on http://127.0.0.1:{PORT}/ model={MODEL} dry_run={DRY_RUN}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
