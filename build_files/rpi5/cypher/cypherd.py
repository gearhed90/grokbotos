#!/usr/bin/env python3
"""cypherd - Cypher's autonomy loop for grokbotos on the Raspberry Pi 5 (stdlib only).

Every tick (45 s by default) cypherd lets its drives drift, looks at the world
(local time, whether Zack is around, the focused app, Do Not Disturb), and when
something changed (or every heartbeat) asks a model to pick ONE action from a
fixed manifest. The validator checks the choice against the locked limits file
(/etc/grokbot/cypher-limits.json, root-owned; Cypher cannot edit it), the
executor runs it, and one JSON line goes to the journal.

Brain: Alpha's Qwen3-VL 8B through cypher-brain-proxy, which lets the camera
filter go first. If Alpha is busy or unreachable, the hosted Grok backup under
a daily dollar cap (when enabled in the limits file); otherwise the tick is
"none". Tokens and keys are read from root-owned files at call time and never
logged or journaled.

Switches (all in ~/.config/cypher, see the cypher CLI):
  KILL         present -> cypherd exits at the next tick and stays off
  muted        present -> no on-screen notes
  pause_until  epoch seconds -> no model calls until then (drives still drift)
"""
import json, os, re, signal, stat, subprocess, sys, threading, time, glob
import urllib.request, urllib.error

E = os.environ.get
HOME = os.path.expanduser("~")
LIMITS_FILE = E("CYPHER_LIMITS", "/etc/grokbot/cypher-limits.json")
TOKEN_FILE = E("CYPHER_BRAIN_TOKEN_FILE", "/etc/grokbot/cypher-brain-token")
XAI_KEY_FILE = E("CYPHER_XAI_KEY_FILE", "/etc/grokbot/xai_key")
CFG_DIR = E("CYPHER_CONFIG_DIR", os.path.join(E("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "cypher"))
STATE_DIR = E("CYPHER_STATE_DIR", os.path.join(E("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "cypher"))
DATA_DIR = E("CYPHER_DATA_DIR", os.path.join(E("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "cypher"))
PERSONA_SYS = E("CYPHER_PERSONA", "/usr/share/grokbot/cypher/persona.md")
NOVAD = E("CYPHER_NOVAD", "http://127.0.0.1:8765")
DRY_RUN = E("CYPHER_DRY_RUN") == "1"          # tests: executor logs instead of acting
INSECURE_OK = E("CYPHER_LIMITS_INSECURE_OK") == "1"   # tests only: limits/token files not root-owned

DRIVES = ("energy", "curiosity", "social", "boredom", "focus")
DEFAULT_DRIFT = {"energy": -0.03, "curiosity": 0.05, "social": 0.06, "boredom": 0.08, "focus": -0.04}
NIGHT_ENERGY = 0.06          # energy recovered per hour during quiet hours (until the sleep phase exists)
EVENT_NUDGES = {"user_active": {"social": -0.15, "boredom": -0.20, "focus": 0.10},
                "user_away": {"focus": -0.10}}
ACTION_EFFECTS = {"journal_thought": {"boredom": -0.05, "curiosity": -0.03},
                  "show_note": {"social": -0.10, "boredom": -0.05},
                  "set_avatar_color": {"boredom": -0.05}}
EX_CONFIG = 78

os.environ.setdefault("TZ", "America/New_York")
time.tzset()

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)

class ConfigError(Exception):
    pass

# ---------- files ----------
def _private_dir(p):
    os.makedirs(p, mode=0o700, exist_ok=True)
    return p

def write_json(path, obj):
    _private_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)

def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

def read_secret(path):
    """Contents of a root:grokbot 0640 secret file, or None. Never logged."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    mode = stat.S_IMODE(st.st_mode)
    if not INSECURE_OK and (st.st_uid != 0 or mode & 0o027):
        log("secret file has unsafe owner/mode, not used:", path)
        return None
    try:
        with open(path) as f:
            return f.read().strip() or None
    except OSError:
        return None

# ---------- limits (locked) and tunables (Cypher may edit, clamped) ----------
def load_limits(path=None):
    path = path or LIMITS_FILE
    try:
        st = os.stat(path)
    except OSError:
        raise ConfigError("limits file missing: " + path)
    if not INSECURE_OK and (st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022):
        raise ConfigError("limits file must be root-owned and not group/other writable")
    try:
        with open(path) as f:
            L = json.load(f)
    except ValueError as e:
        raise ConfigError("limits file is not valid JSON: %s" % e)
    for k in ("enabled", "phase_max", "tick_s", "tick_s_bounds", "heartbeat_s", "drift_bounds_per_hour",
              "quiet_hours", "brain", "actions", "avatar_colors"):
        if k not in L:
            raise ConfigError("limits file lacks " + k)
    lo, hi = L["tick_s_bounds"]
    if not (10 <= lo <= hi):
        raise ConfigError("bad tick_s_bounds")
    for a, spec in L["actions"].items():
        if not isinstance(spec, dict) or "phase" not in spec:
            raise ConfigError("action %s lacks a phase" % a)
    parse_hhmm(L["quiet_hours"][0]); parse_hhmm(L["quiet_hours"][1])
    return L

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def load_tunables(L):
    """tunables.json (optional, editable by Cypher later), clamped to the locked bounds."""
    t = read_json(os.path.join(CFG_DIR, "tunables.json"), {}) or {}
    lo, hi = L["tick_s_bounds"]
    try:
        tick = float(t.get("tick_s", L["tick_s"]))
    except (TypeError, ValueError):
        tick = L["tick_s"]
    dlo, dhi = L["drift_bounds_per_hour"]
    drift = dict(DEFAULT_DRIFT)
    for k, v in (t.get("drift_per_hour") or {}).items():
        if k in drift and isinstance(v, (int, float)):
            drift[k] = clamp(float(v), dlo, dhi)
    return {"tick_s": clamp(tick, lo, hi), "drift_per_hour": drift}

def parse_hhmm(s):
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ConfigError("bad time " + s)
    return h * 60 + m

def in_quiet_hours(L, t=None):
    lt = time.localtime(t)
    now = lt.tm_hour * 60 + lt.tm_min
    a, b = parse_hhmm(L["quiet_hours"][0]), parse_hhmm(L["quiet_hours"][1])
    return (a <= now < b) if a <= b else (now >= a or now < b)

# ---------- drives and mood ----------
def new_state():
    return {"drives": {"energy": 0.7, "curiosity": 0.5, "social": 0.4, "boredom": 0.3, "focus": 0.5},
            "mood": None, "tick": 0, "last_tick": None, "last_call": 0, "last_sig": None,
            "presence": None, "recent": [], "budget": {"date": None, "usd": 0.0},
            "alpha_backoff_until": 0, "last_actions": []}

def apply_delta(drives, delta):
    for k, v in delta.items():
        if k in drives:
            drives[k] = round(clamp(drives[k] + v, 0.0, 1.0), 4)

def drift(drives, drift_per_hour, hours, quiet):
    d = {k: drift_per_hour[k] * hours for k in DRIVES}
    if quiet:
        d["energy"] = NIGHT_ENERGY * hours
    apply_delta(drives, d)

def mood(drives):
    e, c, s, b, f = (drives[k] for k in DRIVES)
    valence = round(0.4 * e + 0.3 * (1 - b) + 0.3 * (1 - s) - 0.5, 3)
    arousal = round(0.5 * c + 0.2 * b + 0.3 * f, 3)
    if e < 0.25: label = "drained"
    elif b > 0.7: label = "restless"
    elif s > 0.75: label = "lonely"
    elif c > 0.7: label = "curious"
    elif f > 0.7: label = "locked-in"
    elif valence > 0.15: label = "content"
    else: label = "idle"
    return {"valence": valence, "arousal": arousal, "label": label}

# ---------- perception ----------
def _run(argv, timeout=4):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None

def _sway_env():
    env = dict(os.environ)
    if not env.get("SWAYSOCK"):
        socks = sorted(glob.glob(os.path.join(E("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "sway-ipc.*.sock")),
                       key=lambda p: os.stat(p).st_mtime, reverse=True)
        if socks:
            env["SWAYSOCK"] = socks[0]
    return env

def _swaymsg(kind):
    try:
        r = subprocess.run(["swaymsg", "-r", "-t", kind], capture_output=True, text=True, timeout=4, env=_sway_env())
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None

def _focused(node):
    if node.get("focused") and node.get("type") in ("con", "floating_con"):
        return node
    for k in ("nodes", "floating_nodes"):
        for n in node.get(k) or []:
            f = _focused(n)
            if f:
                return f
    return None

def perceive(L, now=None):
    now = now or time.time()
    lt = time.localtime(now)
    p = {"local_time": time.strftime("%a %-I:%M %p", lt), "hour": lt.tm_hour,
         "quiet_hours": in_quiet_hours(L, now)}
    locked = bool(_run(["pgrep", "-f", "grokbot-lock-keypad"])) or bool(_run(["pgrep", "-x", "swaylock"]))
    outs = _swaymsg("get_outputs")
    screen_on = any(o.get("power", o.get("dpms", True)) for o in outs) if outs else None
    tree = _swaymsg("get_tree")
    f = _focused(tree) if tree else None
    p["presence"] = "locked" if locked else ("away" if screen_on is False else "active")
    p["focused_app"] = ((f.get("app_id") or (f.get("window_properties") or {}).get("class") or "") if f else "")[:40]
    p["window_title"] = re.sub(r"\s+", " ", (f.get("name") or "") if f else "")[:60]
    mode = _run(["makoctl", "mode"])
    p["dnd"] = bool(mode and "do-not-disturb" in mode.split())
    p["muted"] = os.path.exists(os.path.join(CFG_DIR, "muted"))
    return p

def signature(p, md):
    return "|".join(str(x) for x in (p.get("presence"), p.get("focused_app"), p.get("dnd"),
                                      p.get("quiet_hours"), md["label"]))

# ---------- brain ----------
class BrainBusy(Exception):
    def __init__(self, reason, backoff=False):
        super().__init__(reason); self.reason = reason; self.backoff = backoff

def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def ask_alpha(L, messages):
    B = L["brain"]
    tok = read_secret(TOKEN_FILE)
    if not tok:
        raise BrainBusy("alpha_no_token", backoff=True)
    try:
        j = _post(B["primary_url"].rstrip("/") + "/v1/chat/completions",
                  {"messages": messages, "max_tokens": B["max_output_tokens"], "temperature": 0.7,
                   "response_format": {"type": "json_object"}},
                  {"Authorization": "Bearer " + tok}, B["timeout_s"])
    except urllib.error.HTTPError as e:
        try:
            reason = json.load(e).get("busy") or "http_%d" % e.code
        except Exception:
            reason = "http_%d" % e.code
        # Gaming mode and a missing server last minutes; camera work lasts seconds.
        raise BrainBusy("alpha_" + str(reason), backoff=reason in ("gaming", "upstream_down") or e.code in (401, 403))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BrainBusy("alpha_unreachable", backoff=True)
    return j["choices"][0]["message"]["content"], "alpha", j.get("model", "alpha"), 0.0

def budget_left(L, st, now=None):
    hb = L["brain"].get("hosted_backup") or {}
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if st["budget"].get("date") != today:
        st["budget"] = {"date": today, "usd": 0.0}
    return float(hb.get("daily_budget_usd", 0)) - st["budget"]["usd"]

def ask_hosted(L, st, messages):
    hb = L["brain"].get("hosted_backup") or {}
    if not hb.get("enabled"):
        raise BrainBusy("backup_off")
    # Worst case for one call, so the cap is never crossed.
    chars = sum(len(m["content"]) for m in messages)
    worst = (chars / 3.0) * hb["usd_per_mtok_in"] / 1e6 + L["brain"]["max_output_tokens"] * hb["usd_per_mtok_out"] / 1e6
    if budget_left(L, st) < worst:
        raise BrainBusy("backup_budget_used")
    key = read_secret(XAI_KEY_FILE)
    if not key:
        raise BrainBusy("backup_no_key")
    try:
        j = _post(hb["url"].rstrip("/") + "/chat/completions",
                  {"model": hb["model"], "messages": messages, "max_tokens": L["brain"]["max_output_tokens"],
                   "temperature": 0.7, "response_format": {"type": "json_object"}},
                  {"Authorization": "Bearer " + key}, L["brain"]["timeout_s"])
    except urllib.error.HTTPError as e:
        raise BrainBusy("backup_http_%d" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise BrainBusy("backup_unreachable")
    u = j.get("usage") or {}
    cost = ((u.get("prompt_tokens") or chars / 3.0) * hb["usd_per_mtok_in"]
            + (u.get("completion_tokens") or L["brain"]["max_output_tokens"]) * hb["usd_per_mtok_out"]) / 1e6
    st["budget"]["usd"] = round(st["budget"]["usd"] + cost, 6)
    return j["choices"][0]["message"]["content"], "hosted", hb["model"], round(cost, 6)

def think(L, st, messages, now=None):
    """(content, brain, model, cost_usd, notes). Raises BrainBusy if nothing answered."""
    now = now or time.time()
    notes = []
    if now >= st.get("alpha_backoff_until", 0):
        try:
            return ask_alpha(L, messages) + (notes,)
        except BrainBusy as b:
            notes.append(b.reason)
            if b.backoff:
                st["alpha_backoff_until"] = now + L["brain"]["retry_after_s"]
    else:
        notes.append("alpha_backing_off")
    try:
        return ask_hosted(L, st, messages) + (notes,)
    except BrainBusy as b:
        notes.append(b.reason)
        raise BrainBusy(", ".join(notes))

# ---------- prompt ----------
def persona():
    for p in (os.path.join(CFG_DIR, "persona.md"), PERSONA_SYS):
        try:
            with open(p) as f:
                return f.read().strip()[:1500]
        except OSError:
            pass
    return "You are Cypher. Terse, dry, street-tech."

def allowed_actions(L):
    return {a: s for a, s in L["actions"].items() if s["phase"] <= L["phase_max"]}

MANIFEST_TEXT = {
    "none": "none - do nothing this tick (often right). params: {}",
    "journal_thought": "journal_thought - write a private thought in your journal. params: {\"text\": max %(max_chars)s chars}",
    "show_note": "show_note - show Zack a short note on screen. Only when he is active and it is worth it. params: {\"text\": max %(max_chars)s chars}",
    "set_avatar_color": "set_avatar_color - recolor your on-screen avatar to match your mood. params: {\"color\": one of %(colors)s}",
}

def build_messages(L, st, p):
    acts = allowed_actions(L)
    lines = []
    for a, spec in acts.items():
        if a in MANIFEST_TEXT:
            lines.append("- " + MANIFEST_TEXT[a] % {"max_chars": spec.get("max_chars", ""), "colors": ", ".join(L["avatar_colors"])})
    system = (persona() + "\n\n"
              "You are not a chat assistant. Each tick you look at your state and the world and choose ONE action "
              "from the manifest, or none. Never invent actions or parameters. You cannot change anything in the house, "
              "send messages or run commands.\n"
              "Reply with JSON only: {\"action\": \"...\", \"params\": {...}, \"reason\": \"max 25 words\"}\n\n"
              "Manifest:\n" + "\n".join(lines))
    d = st["drives"]; md = st["mood"] or mood(d)
    last = ", ".join(st["last_actions"][-5:]) or "nothing yet"
    user = ("time: %s (America/New_York)%s\n" % (p["local_time"], ", quiet hours" if p["quiet_hours"] else "")
            + "zack: %s\n" % {"active": "at the screen", "away": "away (screen off)", "locked": "away (screen locked)"}.get(p["presence"], "unknown")
            + "screen: app \"%s\", title \"%s\", do-not-disturb %s%s\n" % (p["focused_app"] or "none", p["window_title"],
                                                                         "on" if p["dnd"] else "off", ", notes muted" if p["muted"] else "")
            + "drives: " + ", ".join("%s %.2f" % (k, d[k]) for k in DRIVES) + "\n"
            + "mood: %s\n" % md["label"]
            + "your last actions: %s\n" % last
            + "Choose.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

# ---------- parse + validate ----------
def parse_choice(text):
    if not isinstance(text, str):
        raise ValueError("no text")
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < i:
        raise ValueError("no JSON object")
    obj = json.loads(s[i:j + 1])
    if not isinstance(obj, dict):
        raise ValueError("not an object")
    return obj

_CTRL = re.compile(r"[\x00-\x1f\x7f]")

def count_recent(st, action, seconds, now):
    return sum(1 for t, a in st["recent"] if a == action and now - t < seconds)

def validate(L, st, p, choice, now=None):
    """(action, params, verdict). verdict is "ok" or "rejected: why"; rejected -> none."""
    now = now or time.time()
    a = choice.get("action")
    params = choice.get("params") if isinstance(choice.get("params"), dict) else {}
    acts = allowed_actions(L)
    if not isinstance(a, str) or a not in L["actions"]:
        return "none", {}, "rejected: unknown action %r" % (str(a)[:40],)
    if a not in acts:
        return "none", {}, "rejected: %s is not unlocked (phase %d)" % (a, L["phase_max"])
    spec = acts[a]
    if a == "none":
        return "none", {}, "ok"
    if spec.get("per_hour") is not None and count_recent(st, a, 3600, now) >= spec["per_hour"]:
        return "none", {}, "rejected: %s hourly cap" % a
    if spec.get("per_day") is not None and count_recent(st, a, 86400, now) >= spec["per_day"]:
        return "none", {}, "rejected: %s daily cap" % a
    if a in ("journal_thought", "show_note"):
        text = params.get("text")
        if not isinstance(text, str) or not _CTRL.sub(" ", text).strip():
            return "none", {}, "rejected: %s needs text" % a
        text = re.sub(r"\s+", " ", _CTRL.sub(" ", text)).strip()
        if len(text) > spec["max_chars"]:
            return "none", {}, "rejected: %s text over %d chars" % (a, spec["max_chars"])
        if a == "show_note":
            if p.get("muted"): return "none", {}, "rejected: notes muted"
            if p.get("dnd"): return "none", {}, "rejected: do not disturb"
            if p.get("quiet_hours"): return "none", {}, "rejected: quiet hours"
            if p.get("presence") != "active": return "none", {}, "rejected: zack is away"
        return a, {"text": text}, "ok"
    if a == "set_avatar_color":
        c = params.get("color")
        if c not in L["avatar_colors"]:
            return "none", {}, "rejected: color %r not allowed" % (str(c)[:20],)
        return a, {"color": c}, "ok"
    return "none", {}, "rejected: no executor for %s" % a

# ---------- act ----------
def execute(action, params):
    if action in ("none", "journal_thought"):
        return "ok"
    if DRY_RUN:
        log("DRY-RUN", action, json.dumps(params)); return "ok (dry run)"
    if action == "show_note":
        r = subprocess.run(["notify-send", "-a", "Cypher", "-t", "9000", "Cypher", params["text"]],
                           capture_output=True, timeout=5)
        return "ok" if r.returncode == 0 else "notify failed"
    if action == "set_avatar_color":
        try:
            _post(NOVAD + "/api/avatar", {"color": params["color"]}, {}, 5)
            return "ok"
        except Exception as e:
            return "avatar failed: " + type(e).__name__
    return "no executor"

# ---------- journal ----------
def journal(entry, now=None):
    d = _private_dir(os.path.join(DATA_DIR, "journal"))
    path = os.path.join(d, time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))

# ---------- the tick ----------
def tick(L, st, now=None, perceive_fn=perceive):
    """One tick. Returns the journal entry if a model was asked (or a choice rejected), else None."""
    now = now or time.time()
    tun = load_tunables(L)
    last = st.get("last_tick") or now
    hours = clamp((now - last) / 3600.0, 0, 1.0)     # a long gap (power off) counts as at most an hour
    p = perceive_fn(L, now)
    drift(st["drives"], tun["drift_per_hour"], hours, p["quiet_hours"])
    if st.get("presence") and st["presence"] != p["presence"]:
        apply_delta(st["drives"], EVENT_NUDGES["user_active" if p["presence"] == "active" else "user_away"])
    st["presence"] = p["presence"]
    st["mood"] = mood(st["drives"])
    st["tick"] += 1
    st["last_tick"] = now
    st["recent"] = [r for r in st["recent"] if now - r[0] < 86400]
    paused = (read_json(os.path.join(CFG_DIR, "pause_until"), 0) or 0)
    if isinstance(paused, (int, float)) and now < paused:
        return None
    sig = signature(p, st["mood"])
    if sig == st.get("last_sig") and now - st.get("last_call", 0) < L["heartbeat_s"]:
        return None
    st["last_sig"] = sig; st["last_call"] = now
    before = dict(st["drives"])
    messages = build_messages(L, st, p)
    entry = {"ts": iso(now), "tick": st["tick"], "perception": {k: p[k] for k in
             ("local_time", "presence", "focused_app", "window_title", "dnd", "muted", "quiet_hours")},
             "drives_before": before, "mood": st["mood"]["label"]}
    t0 = time.monotonic()
    try:
        content, brain, model, cost, notes = think(L, st, messages, now)
    except BrainBusy as b:
        entry.update({"brain": "none", "choice": {"action": "none"}, "reason": "no brain available: " + str(b),
                      "validator": "skipped", "result": "skipped"})
        journal(entry, now); return entry
    entry.update({"brain": brain, "model": model, "latency_ms": int((time.monotonic() - t0) * 1000)})
    if cost: entry["cost_usd"] = cost
    if notes: entry["brain_notes"] = notes
    try:
        choice = parse_choice(content)
    except (ValueError, json.JSONDecodeError) as e:
        entry.update({"choice": {"action": "none"}, "reason": "", "validator": "rejected: unparseable reply (%s)" % e,
                      "result": "skipped"})
        journal(entry, now); return entry
    action, params, verdict = validate(L, st, p, choice, now)
    result = execute(action, params) if verdict == "ok" else "skipped"
    if verdict == "ok" and action != "none":
        st["recent"].append([now, action])
        apply_delta(st["drives"], ACTION_EFFECTS.get(action, {}))
    st["last_actions"] = (st["last_actions"] + [action])[-10:]
    st["mood"] = mood(st["drives"])
    reason = choice.get("reason") if isinstance(choice.get("reason"), str) else ""
    entry.update({"choice": {"action": action, "params": params}, "reason": _CTRL.sub(" ", reason)[:300],
                  "validator": verdict, "result": result, "drives_after": dict(st["drives"])})
    if verdict != "ok":
        entry["model_choice"] = str(choice.get("action"))[:40]
    journal(entry, now)
    return entry

# ---------- main loop ----------
def killed(L):
    return os.path.exists(os.path.join(CFG_DIR, "KILL")) or not L.get("enabled")

def main():
    try:
        L = load_limits()
    except ConfigError as e:
        log("not starting:", e); sys.exit(EX_CONFIG)
    state_path = os.path.join(STATE_DIR, "drives.json")
    st = new_state()
    saved = read_json(state_path)
    if isinstance(saved, dict) and isinstance(saved.get("drives"), dict):
        st.update({k: v for k, v in saved.items() if k in st})
        for k in DRIVES:
            st["drives"][k] = clamp(float(st["drives"].get(k, 0.5)), 0, 1)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    log("cypherd up: phase %d, tick %ss" % (L["phase_max"], load_tunables(L)["tick_s"]))
    while not stop.is_set():
        try:
            L = load_limits()
        except ConfigError as e:
            log("limits became invalid, stopping:", e); write_json(state_path, st); sys.exit(EX_CONFIG)
        if killed(L):
            log("kill switch set, stopping"); write_json(state_path, st)
            journal({"ts": iso(time.time()), "event": "stopped", "why": "kill switch"})
            return
        try:
            e = tick(L, st)
            if e:
                log("tick %d: %s via %s (%s)" % (e["tick"], e["choice"]["action"], e.get("brain"), e.get("validator")))
        except Exception as ex:      # one bad tick must not kill the loop; the journal shows the gap
            log("tick error:", type(ex).__name__, str(ex)[:200])
        write_json(state_path, st)
        stop.wait(load_tunables(L)["tick_s"])
    write_json(state_path, st)
    log("cypherd stopped")

if __name__ == "__main__":
    main()
