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

Phase 2:
  * Failover: one mind lease on Alpha's proxy. The deck ("cypher") always wins
    it; a standby cypherd on Alpha (CYPHER_HOST=alpha) takes it only when the
    deck stopped cleanly or went dark (lease expired and the deck does not
    answer), and hands it back the moment the deck returns. State, memories and
    journal are pushed to Alpha every tick and pulled back on hand-back.
  * Camera feed: sanitized events from cypher-camfeed via the proxy. They move
    drives and get journaled; the validator lets a camera tick do nothing but
    journal, and never allows a camera, light or house action.
  * Local fallback: Qwen2.5 3B on the deck (cypher-llm, 127.0.0.1:8081) when
    Alpha is busy or away, before the hosted backup.
  * Nightly sleep: the day's journal condensed into memories; preference notes
    and drift adjusted within the locked limits, every change versioned.

Phase 2.1: the manifest only offers actions that would pass right now (caps,
mute, DND, quiet hours, presence); refused attempts show in "your last
actions"; the avatar color only changes when the mood does.

Phase 3 (all capped in the limits file; deck only unless noted):
  * message_zack: a short ntfy.sh push to Zack's phone (secret topic in a
    root:grokbot 0640 file, never logged); never in quiet hours.
  * glance_screen: one low-res grim screenshot of the deck's own screen, sent
    only to Alpha's proxy (Qwen3-VL) for a short description, deleted at once.
    Never the hosted backup. Only while Zack is at the screen, never on a window
    whose title looks private.
  * look_up: a Wikipedia summary (allowlisted hosts only, read-only), on the
    deck or Alpha. Findings go to the journal and the next prompts.
  * request_account: ask Zack for an account on a named service. Writes a
    journal entry and a pending request, and pings his phone once. Nova
    creates accounts only after Zack approves. Cypher never signs up, never
    holds a password, and must not share its email. The phone ping does not
    count against message_zack's caps. Deck only; never in quiet hours.

Switches (all in ~/.config/cypher, see the cypher CLI):
  KILL         present -> cypherd exits at the next tick and stays off
  muted        present -> no on-screen notes
  pause_until  epoch seconds -> no model calls until then (drives still drift)
"""
import json, os, re, signal, stat, subprocess, sys, threading, time, glob
import urllib.request, urllib.error, urllib.parse

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
NTFY_TOPIC_FILE = E("CYPHER_NTFY_TOPIC_FILE", "/etc/grokbot/cypher-ntfy-topic")
INSECURE_OK = E("CYPHER_LIMITS_INSECURE_OK") == "1"   # tests only: limits/token files not root-owned
HOST = E("CYPHER_HOST", "deck")              # "deck" (the Pi) or "alpha" (the standby on Alpha)
HOLDER = "alpha" if HOST == "alpha" else "cypher"
TRUST_OWNER = E("CYPHER_TRUST_OWNER") == "1"  # Alpha: 0600 files owned by this user count as locked

DRIVES = ("energy", "curiosity", "social", "boredom", "focus")
WEEK_S = 7 * 86400            # retention for recent actions, so per_week caps work
DEFAULT_DRIFT = {"energy": -0.03, "curiosity": 0.05, "social": 0.06, "boredom": 0.08, "focus": -0.04}
NIGHT_ENERGY = 0.06          # energy recovered per hour during quiet hours (until the sleep phase exists)
EVENT_NUDGES = {"user_active": {"social": -0.15, "boredom": -0.20, "focus": 0.10},
                "user_away": {"focus": -0.10}}
ACTION_EFFECTS = {"journal_thought": {"boredom": -0.05, "curiosity": -0.03},
                  "show_note": {"social": -0.10, "boredom": -0.05},
                  "set_avatar_color": {"boredom": -0.02},     # small: not the default boredom outlet
                  "message_zack": {"social": -0.15, "boredom": -0.03},
                  "glance_screen": {"curiosity": -0.08, "boredom": -0.05},
                  "look_up": {"curiosity": -0.10, "boredom": -0.06},
                  "request_account": {"social": -0.08, "curiosity": -0.04}}
DECK_ONLY = ("show_note", "set_avatar_color", "message_zack", "glance_screen", "request_account")
BLOCKS = ("camera", "sleep", "failover", "ntfy", "screen", "lookup")
EX_CONFIG = 78
CAMERA_NUDGES = {"family": {"social": -0.10, "boredom": -0.05}, "person": {"curiosity": 0.05, "focus": 0.03},
                 "stranger": {"curiosity": 0.10, "focus": 0.10, "energy": -0.02},
                 "alert": {"focus": 0.10, "curiosity": 0.05}, "vehicle": {"curiosity": 0.03},
                 "arrival_start": {"curiosity": 0.05}, "arrival_end": {"social": -0.03},
                 "unconfirmed": {"curiosity": 0.02}}
# Never an action, whatever the limits file says.
HOUSE_WORDS = re.compile(r"camera|light|lock|door|garage|alarm|siren|ptz|record|thermostat|scene|hass|home.?assistant|switch", re.I)
# Known in persona.md only. Never placed in a journal line, ntfy body or request file by cypherd.
ACCOUNT_EMAIL = "s4j6vbnk+cypher@mail.grokbot.com"
_PASSWORD_WORD = re.compile(r"password", re.I)
_CRED_URL = re.compile(
    r"https?://[^\s/]*:[^\s/]*@"          # https://user:pass@host
    r"|https?://[^\s/]+@"                  # https://user@host
    r"|[?&](?:password|passwd|token|secret|api[_-]?key|access[_-]?token)=",
    re.I)
_ACCOUNT_EMAIL_RE = re.compile(r"s4j6vbnk\+cypher@mail\.grokbot\.com|@mail\.grokbot\.com", re.I)
_OUTBOX = []          # journal entries not yet pushed to Alpha
_EPOCH = [None]       # current lease epoch, for journal ids

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
    if not INSECURE_OK and not ((st.st_uid == 0 and not mode & 0o027) or
                                (TRUST_OWNER and st.st_uid == os.getuid() and not mode & 0o077)):
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
    owner_ok = st.st_uid == 0 or (TRUST_OWNER and st.st_uid == os.getuid())
    if not INSECURE_OK and (not owner_ok or stat.S_IMODE(st.st_mode) & 0o022):
        raise ConfigError("limits file must be root-owned and not group/other writable")
    try:
        with open(path) as f:
            L = json.load(f)
    except ValueError as e:
        raise ConfigError("limits file is not valid JSON: %s" % e)
    return validate_limits(L)

def validate_limits(L):
    if not isinstance(L, dict):
        raise ConfigError("limits must be an object")
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
        if HOUSE_WORDS.search(a):
            raise ConfigError("action %s looks like a camera or house control; never allowed" % a)
    for blk in BLOCKS:
        if blk in L and not isinstance(L[blk], dict):
            raise ConfigError(blk + " must be an object")
    if isinstance(L.get("sleep"), dict):
        parse_hhmm(L["sleep"].get("at", "04:00"))
    L["_quiet_nights"] = quiet_nights(L["quiet_hours"])
    return L

def host_overrides(L):
    """On Alpha there is no deck to show notes on and no hosted key or local model."""
    if HOST != "alpha":
        return L
    L = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"}))
    for a in DECK_ONLY:
        if a in L["actions"]:
            L["actions"][a]["phase"] = 99
    L["brain"].setdefault("hosted_backup", {})["enabled"] = False
    L["brain"].setdefault("local", {})["enabled"] = False
    L["_quiet_nights"] = quiet_nights(L["quiet_hours"])
    return L

def current_limits(st):
    """The locked limits. On Alpha, the deck's own limits as last synced (so a sudo
    edit on the deck reaches the standby), else Alpha's bootstrap copy."""
    L = load_limits()
    if HOST == "alpha" and isinstance(st.get("deck_limits"), dict):
        try:
            L = validate_limits(json.loads(json.dumps(st["deck_limits"])))
        except (ConfigError, ValueError, KeyError, TypeError) as e:
            log("synced limits invalid, using Alpha's copy:", e)
    return host_overrides(L)

def phase_on(L, block):
    b = L.get(block) if block in BLOCKS else (L["brain"].get(block) or {})
    return isinstance(b, dict) and bool(b.get("enabled")) and L["phase_max"] >= b.get("phase", 2)

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

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

def quiet_nights(q):
    """Quiet-hours schedule -> {day: (start_min, end_min) or None}, keyed by the day the
    night STARTS on (a 23:00-06:00 window on "fri" is Friday 11 PM to Saturday 6 AM).
      ["23:00", "06:00"]                              every night
      {"default": ["23:00", "06:00"], "nights": {"fri": null, "sat": null}}
                                                      per-night override; null = no quiet hours"""
    if isinstance(q, list):
        q = {"default": q}
    if not isinstance(q, dict):
        raise ConfigError("quiet_hours must be a list or an object")
    def win(w):
        if w is None:
            return None
        if not (isinstance(w, list) and len(w) == 2):
            raise ConfigError("a quiet-hours window is [\"HH:MM\", \"HH:MM\"] or null")
        return (parse_hhmm(w[0]), parse_hhmm(w[1]))
    default = win(q.get("default"))
    nights = q.get("nights") or {}
    if not isinstance(nights, dict) or any(k not in DAYS for k in nights):
        raise ConfigError("quiet_hours.nights keys must be mon..sun")
    return {d: (win(nights[d]) if d in nights else default) for d in DAYS}

def in_quiet_hours(L, t=None):
    sched = L.get("_quiet_nights") or quiet_nights(L["quiet_hours"])
    lt = time.localtime(t)
    now = lt.tm_hour * 60 + lt.tm_min
    today, yesterday = DAYS[lt.tm_wday], DAYS[(lt.tm_wday - 1) % 7]
    w = sched[today]
    if w:
        a, b = w
        if a <= b and a <= now < b: return True
        if a > b and now >= a: return True          # tonight's window, before midnight
    w = sched[yesterday]
    if w:
        a, b = w
        if a > b and now < b: return True           # last night's window, after midnight
    return False

# ---------- drives and mood ----------
def new_state():
    return {"drives": {"energy": 0.7, "curiosity": 0.5, "social": 0.4, "boredom": 0.3, "focus": 0.5},
            "mood": None, "tick": 0, "last_tick": None, "last_call": 0, "last_sig": None,
            "presence": None, "recent": [], "budget": {"date": None, "usd": 0.0},
            "alpha_backoff_until": 0, "last_actions": [], "local_backoff_until": 0,
            "cam_seq": None, "last_sleep": None, "lease_epoch": None, "holding": False,
            "merged_since": "", "outbox": [], "deck_limits": None,
            "avatar_color": None, "color_mood": None, "found": []}

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

def perceive_alpha(L, now=None):
    """On Alpha the deck is dark: only time, quiet hours and the mute switch."""
    now = now or time.time()
    lt = time.localtime(now)
    return {"local_time": time.strftime("%a %-I:%M %p", lt), "hour": lt.tm_hour,
            "quiet_hours": in_quiet_hours(L, now), "presence": "deck_offline", "focused_app": "",
            "window_title": "", "dnd": False, "muted": os.path.exists(os.path.join(CFG_DIR, "muted"))}

def signature(p, md):
    cam = max([e.get("seq", 0) for e in p.get("camera") or []] or [0])
    return "|".join(str(x) for x in (p.get("presence"), p.get("focused_app"), p.get("dnd"),
                                      p.get("quiet_hours"), md["label"], cam))

# ---------- Alpha API (lease, sync, camera feed) ----------
def alpha_urls(L):
    B = L["brain"]
    return [u.rstrip("/") for u in (B.get("primary_urls") or [B["primary_url"]])]

def alpha_api(L, method, path, body=None, timeout=6):
    """(status, json) from the proxy, trying LAN then tailnet. Raises BrainBusy if neither answers."""
    tok = read_secret(TOKEN_FILE)
    if not tok:
        raise BrainBusy("alpha_no_token")
    for u in alpha_urls(L):
        req = urllib.request.Request(u + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except Exception:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    raise BrainBusy("alpha_unreachable")

# ---------- camera feed (read-only) ----------
_CAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
_NAME_RE = re.compile(r"^[A-Z][a-z]{1,15}$")
_T_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_REASON_RE = re.compile(r"^[a-z ,/-]{1,60}$")

def clean_event(e):
    """Re-check every field the feed sends; anything odd drops the event."""
    if not isinstance(e, dict) or not _CAM_RE.match(str(e.get("camera", ""))) or not _T_RE.match(str(e.get("time", ""))):
        return None
    if e.get("kind") not in CAMERA_NUDGES and e.get("kind") not in ("motion", "nothing", "motion_dropped", "cooldown",
                                                                      "cross_trigger", "no_alert", "review"):
        return None
    out = {"seq": e["seq"] if isinstance(e.get("seq"), int) else 0, "time": e["time"], "camera": e["camera"],
           "kind": e["kind"], "alerted": e.get("alerted") if isinstance(e.get("alerted"), bool) else None,
           "source": e.get("source") if e.get("source") in ("gate", "review", "shadow", "cloud") else None}
    names = [n for n in (e.get("names") or []) if isinstance(n, str) and _NAME_RE.match(n)][:4]
    if names:
        out["names"] = names
    if e.get("guess") in ("person", "vehicle", "motion"):
        out["guess"] = e["guess"]
    if isinstance(e.get("reason"), str) and _REASON_RE.match(e["reason"]):
        out["reason"] = e["reason"]
    return out

def camera_step(L, st, now):
    """New interesting camera events since the last tick (at most max_per_tick)."""
    if not phase_on(L, "camera"):
        return []
    C = L["camera"]
    since = st.get("cam_seq")
    try:
        code, j = alpha_api(L, "GET", "/camera/events?since=%d&limit=50" % (since or 0), timeout=5)
    except BrainBusy:
        return []
    if code != 200 or not isinstance(j, dict):
        return []
    last = j.get("last_seq") if isinstance(j.get("last_seq"), int) else 0
    st["cam_seq"] = last          # also resets if the feed was reset (last < since)
    window = C.get("first_lookback_s", 43200) if since is None else C.get("max_age_s", 1800)
    keep = []
    for e in j.get("events") or []:
        e = clean_event(e)
        if not e or e["kind"] == "nothing" or e["kind"] not in C.get("react_kinds", list(CAMERA_NUDGES)):
            continue
        try:
            t = time.mktime(time.strptime(e["time"], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if now - t <= window:
            keep.append(e)
    return keep[-int(C.get("max_per_tick", 5)):]

def camera_line(evs):
    out = []
    for e in evs:
        kind = e["kind"].replace("_", " ")
        if e["kind"] == "unconfirmed":
            kind = "unconfirmed motion (detector guess: %s; not checked, nobody identified)" % e.get("guess", "motion")
        elif e["kind"] == "nothing":
            kind = "nothing (no one came or went%s)" % ("; " + e["reason"] if e.get("reason") else "")
        bits = [e["time"][11:16], e["camera"], kind]
        if e.get("names"): bits.append("(" + ", ".join(e["names"]) + ")")
        if e.get("alerted") is True: bits.append("- Zack was alerted")
        out.append(" ".join(bits))
    return "; ".join(out)

# ---------- brain ----------
class BrainBusy(Exception):
    def __init__(self, reason, backoff=False):
        super().__init__(reason); self.reason = reason; self.backoff = backoff

def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def ask_alpha(L, messages, max_tokens=None):
    B = L["brain"]
    tok = read_secret(TOKEN_FILE)
    if not tok:
        raise BrainBusy("alpha_no_token", backoff=True)
    for i, u in enumerate(alpha_urls(L)):
        try:
            j = _post(u + "/v1/chat/completions",
                      {"messages": messages, "max_tokens": max_tokens or B["max_output_tokens"], "temperature": 0.7,
                       "response_format": {"type": "json_object"}},
                      {"Authorization": "Bearer " + tok}, B["timeout_s"])
            return j["choices"][0]["message"]["content"], "alpha", j.get("model", "alpha"), 0.0
        except urllib.error.HTTPError as e:
            try:
                reason = json.load(e).get("busy") or "http_%d" % e.code
            except Exception:
                reason = "http_%d" % e.code
            # Gaming mode and a missing server last minutes; camera work lasts seconds.
            raise BrainBusy("alpha_" + str(reason), backoff=reason in ("gaming", "upstream_down") or e.code in (401, 403))
        except (urllib.error.URLError, OSError) as e:
            if isinstance(e, TimeoutError):
                raise BrainBusy("alpha_timeout", backoff=True)     # it answered the door but not in time
            continue
    raise BrainBusy("alpha_unreachable", backoff=True)

def ask_local(L, st, messages, max_tokens=None, now=None):
    """The deck's own small model (cypher-llm on 127.0.0.1). Free, slow, always home."""
    lc = L["brain"].get("local") or {}
    if not phase_on(L, "local"):
        raise BrainBusy("local_off")
    if (now or time.time()) < st.get("local_backoff_until", 0):
        raise BrainBusy("local_backing_off")
    try:
        j = _post(lc["url"].rstrip("/") + "/v1/chat/completions",
                  {"messages": messages, "max_tokens": max_tokens or lc.get("max_output_tokens", 120),
                   "temperature": 0.7, "response_format": {"type": "json_object"}, "cache_prompt": True},
                  {}, lc.get("timeout_s", 120))
    except urllib.error.HTTPError as e:
        raise BrainBusy("local_http_%d" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        st["local_backoff_until"] = (now or time.time()) + 60     # same box: cheap to retry soon
        raise BrainBusy("local_unreachable")
    return j["choices"][0]["message"]["content"], "local", lc.get("model", "local"), 0.0

def budget_left(L, st, now=None):
    hb = L["brain"].get("hosted_backup") or {}
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if st["budget"].get("date") != today:
        st["budget"] = {"date": today, "usd": 0.0}
    return float(hb.get("daily_budget_usd", 0)) - st["budget"]["usd"]

def ask_hosted(L, st, messages, max_tokens=None):
    hb = L["brain"].get("hosted_backup") or {}
    if not hb.get("enabled"):
        raise BrainBusy("backup_off")
    # Worst case for one call, so the cap is never crossed.
    chars = sum(len(m["content"]) for m in messages)
    mt = max_tokens or L["brain"]["max_output_tokens"]
    worst = (chars / 3.0) * hb["usd_per_mtok_in"] / 1e6 + mt * hb["usd_per_mtok_out"] / 1e6
    if budget_left(L, st) < worst:
        raise BrainBusy("backup_budget_used")
    key = read_secret(XAI_KEY_FILE)
    if not key:
        raise BrainBusy("backup_no_key")
    try:
        j = _post(hb["url"].rstrip("/") + "/chat/completions",
                  {"model": hb["model"], "messages": messages, "max_tokens": mt,
                   "temperature": 0.7, "response_format": {"type": "json_object"}},
                  {"Authorization": "Bearer " + key}, L["brain"]["timeout_s"])
    except urllib.error.HTTPError as e:
        raise BrainBusy("backup_http_%d" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise BrainBusy("backup_unreachable")
    u = j.get("usage") or {}
    cost = ((u.get("prompt_tokens") or chars / 3.0) * hb["usd_per_mtok_in"]
            + (u.get("completion_tokens") or mt) * hb["usd_per_mtok_out"]) / 1e6
    st["budget"]["usd"] = round(st["budget"]["usd"] + cost, 6)
    return j["choices"][0]["message"]["content"], "hosted", hb["model"], round(cost, 6)

def think(L, st, messages, now=None, max_tokens=None):
    """(content, brain, model, cost_usd, notes): Alpha, then the deck's local model, then
    the hosted backup. Raises BrainBusy if nothing answered."""
    now = now or time.time()
    notes = []
    if now >= st.get("alpha_backoff_until", 0):
        try:
            return ask_alpha(L, messages, max_tokens) + (notes,)
        except BrainBusy as b:
            notes.append(b.reason)
            if b.backoff:
                st["alpha_backoff_until"] = now + L["brain"]["retry_after_s"]
    else:
        notes.append("alpha_backing_off")
    if phase_on(L, "local"):
        try:
            return ask_local(L, st, messages, max_tokens, now) + (notes,)
        except BrainBusy as b:
            notes.append(b.reason)
    try:
        return ask_hosted(L, st, messages, max_tokens) + (notes,)
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
    "set_avatar_color": "set_avatar_color - recolor your on-screen avatar, only when your mood has really changed. params: {\"color\": one of %(colors)s}",
    "message_zack": "message_zack - push a short message to Zack's phone. Rare: only something he would want to know now "
                    "(something broken, a finding worth his time). Never small talk, greetings or mood updates. params: {\"text\": max %(max_chars)s chars}",
    "glance_screen": "glance_screen - take one look at what is on your own screen right now; a short description comes back next tick. params: {}",
    "look_up": "look_up - look a topic up on Wikipedia; the summary comes back next tick. params: {\"topic\": max %(max_chars)s chars}",
    "request_account": "request_account - ask Zack for an account on a service. This only ASKS; you cannot sign up and must not share your email address. Nova creates an account only after Zack approves. params: {\"service\": short name, max 40 chars, \"why\": max 160 chars}",
}
CAMERA_RULES = ("Only what the line says happened. 'unconfirmed' means motion nobody has checked: do not guess who it was. "
                "Never invent doors opening, people coming or going, or who someone is (or is not) unless a name is in the line.")

def build_messages(L, st, p, now=None):
    now = now or time.time()
    acts = allowed_actions(L)
    if p.get("camera"):            # camera ticks: journal or nothing (the validator enforces it too)
        acts = {a: s for a, s in acts.items() if a in ("none", "journal_thought")}
    acts = {a: s for a, s in acts.items() if not blocked(L, st, p, a, now)}   # only what would pass right now
    lines = []
    for a, spec in acts.items():
        if a in MANIFEST_TEXT:
            lines.append("- " + MANIFEST_TEXT[a] % {"max_chars": spec.get("max_chars", ""), "colors": ", ".join(L["avatar_colors"])})
    system = (persona() + "\n\n"
              "You are not a chat assistant. Each tick you look at your state and the world and choose ONE action "
              "from the manifest, or none. Never invent actions or parameters. You cannot change anything in the house, "
              "send messages or run commands. Never share your email address or use it to sign up; "
              "request_account only asks Zack, and must not include the address.\n"
              "Reply with JSON only: {\"action\": \"...\", \"params\": {...}, \"reason\": \"max 25 words\"}\n\n"
              "Manifest:\n" + "\n".join(lines))
    d = st["drives"]; md = st["mood"] or mood(d)
    last = ", ".join(st["last_actions"][-5:]) or "nothing yet"
    user = ("time: %s (America/New_York)%s\n" % (p["local_time"], ", quiet hours" if p["quiet_hours"] else "")
            + "zack: %s\n" % {"active": "at the screen", "away": "away (screen off)", "locked": "away (screen locked)",
                               "deck_offline": "unknown (the deck is off; you are running on Alpha, journal only)"}.get(p["presence"], "unknown")
            + "screen: app \"%s\", title \"%s\", do-not-disturb %s%s\n" % (p["focused_app"] or "none", p["window_title"],
                                                                         "on" if p["dnd"] else "off", ", notes muted" if p["muted"] else "")
            + "drives: " + ", ".join("%s %.2f" % (k, d[k]) for k in DRIVES) + "\n"
            + "mood: %s\n" % md["label"]
            + "your last actions: %s\n" % last
            + found_lines(st, now)
            + ("cameras (read-only feed; you cannot control cameras, lights or anything in the house): %s\n"
               "If it matters to you, write a short journal_thought about it; otherwise none. %s\n"
               % (camera_line(p["camera"]), CAMERA_RULES) if p.get("camera") else "")
            + memory_lines()
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

PRIVATE_TITLE = re.compile(r"pass(word|phrase)|1password|bitwarden|keepass|vault|bank|log ?in|sign ?in|wallet|token|secret|private|incognito|otp|2fa", re.I)

def mood_label(st):
    return (st.get("mood") or mood(st["drives"]))["label"]

def blocked(L, st, p, a, now):
    """Why action a would be refused right now whatever its params (caps, switches, presence), or None.
    The manifest leaves such actions out; the validator refuses them with the same words."""
    spec = L["actions"].get(a) or {}
    if spec.get("per_hour") is not None and count_recent(st, a, 3600, now) >= spec["per_hour"]:
        return "%s hourly cap" % a
    if spec.get("per_day") is not None and count_recent(st, a, 86400, now) >= spec["per_day"]:
        return "%s daily cap" % a
    if spec.get("per_week") is not None and count_recent(st, a, WEEK_S, now) >= spec["per_week"]:
        return "%s weekly cap" % a
    if a == "show_note":
        if p.get("muted"): return "notes muted"
        if p.get("dnd"): return "do not disturb"
        if p.get("quiet_hours"): return "quiet hours"
        if p.get("presence") != "active": return "zack is away"
    if a == "set_avatar_color" and st.get("color_mood") is not None and mood_label(st) == st["color_mood"]:
        return "no mood change since the last color"
    if a == "message_zack":
        if not phase_on(L, "ntfy"): return "phone messages off"
        if p.get("quiet_hours"): return "quiet hours"
        if not read_secret(NTFY_TOPIC_FILE): return "no phone topic set up"
    if a == "glance_screen":
        if not phase_on(L, "screen"): return "screen glances off"
        if p.get("presence") != "active": return "zack is away"
        if PRIVATE_TITLE.search(p.get("window_title") or "") or PRIVATE_TITLE.search(p.get("focused_app") or ""):
            return "private window"
    if a == "look_up" and not phase_on(L, "lookup"):
        return "look-ups off"
    if a == "request_account":
        if p.get("quiet_hours"): return "quiet hours"
    return None

_TOPIC_RE = re.compile(r"^[\w][\w '().,:-]*$", re.U)

def validate(L, st, p, choice, now=None):
    """(action, params, verdict). verdict is "ok" or "rejected: why"; rejected -> none."""
    now = now or time.time()
    a = choice.get("action")
    params = choice.get("params") if isinstance(choice.get("params"), dict) else {}
    acts = allowed_actions(L)
    if isinstance(a, str) and HOUSE_WORDS.search(a):
        return "none", {}, "rejected: camera and house controls are never available"
    if not isinstance(a, str) or a not in L["actions"]:
        return "none", {}, "rejected: unknown action %r" % (str(a)[:40],)
    if a not in acts:
        return "none", {}, "rejected: %s is not unlocked (phase %d)" % (a, L["phase_max"])
    spec = acts[a]
    if a == "none":
        return "none", {}, "ok"
    if p.get("camera") and a != "journal_thought":
        return "none", {}, "rejected: camera events get journal and mood reactions only"
    why = blocked(L, st, p, a, now)
    if why:
        return "none", {}, "rejected: " + why
    if a in ("journal_thought", "show_note", "message_zack"):
        text = params.get("text")
        if not isinstance(text, str) or not _CTRL.sub(" ", text).strip():
            return "none", {}, "rejected: %s needs text" % a
        text = re.sub(r"\s+", " ", _CTRL.sub(" ", text)).strip()
        if len(text) > spec["max_chars"]:
            return "none", {}, "rejected: %s text over %d chars" % (a, spec["max_chars"])
        return a, {"text": text}, "ok"
    if a == "set_avatar_color":
        c = params.get("color")
        if c not in L["avatar_colors"]:
            return "none", {}, "rejected: color %r not allowed" % (str(c)[:20],)
        if c == st.get("avatar_color"):
            return "none", {}, "rejected: already %s" % c
        return a, {"color": c}, "ok"
    if a == "glance_screen":
        return a, {}, "ok"
    if a == "look_up":
        t = params.get("topic")
        t = re.sub(r"\s+", " ", _CTRL.sub(" ", t)).strip() if isinstance(t, str) else ""
        if not t or len(t) > spec.get("max_chars", 60) or not _TOPIC_RE.match(t) or _URL.search(t):
            return "none", {}, "rejected: look_up needs a plain topic (max %d chars)" % spec.get("max_chars", 60)
        return a, {"topic": t}, "ok"
    if a == "request_account":
        svc_n = int(spec.get("max_service_chars", 40))
        why_n = int(spec.get("max_why_chars", 160))
        service = re.sub(r"\s+", " ", _CTRL.sub(" ", params.get("service") or "")).strip() if isinstance(params.get("service"), str) else ""
        why = re.sub(r"\s+", " ", _CTRL.sub(" ", params.get("why") or "")).strip() if isinstance(params.get("why"), str) else ""
        if not service or len(service) > svc_n:
            return "none", {}, "rejected: request_account needs a service name (max %d chars)" % svc_n
        if not why or len(why) > why_n:
            return "none", {}, "rejected: request_account needs a why (max %d chars)" % why_n
        if request_forbidden(service, why):
            return "none", {}, "rejected: request_account cannot mention passwords, house controls or credential URLs"
        return a, {"service": service, "why": why}, "ok"
    return "none", {}, "rejected: no executor for %s" % a

# ---------- act ----------
def execute(action, params, L=None, st=None, p=None):
    """Run a validated action. Returns the result string; look_up and glance_screen
    also leave what they found in st["found"]."""
    if action in ("none", "journal_thought"):
        return "ok"
    if action == "look_up":
        return do_look_up(L, st, params["topic"])
    if action == "glance_screen":
        return do_glance(L, st, p)
    if action == "request_account":
        return do_request_account(L, st, params)
    if DRY_RUN:
        log("DRY-RUN", action, json.dumps(params)); return "ok (dry run)"
    if action == "message_zack":
        return send_ntfy(L, params["text"])
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

# ---------- phase 3: phone, screen glances, look-ups ----------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None

def _http(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    """(status, bytes). Only https, only allowlisted hosts, no redirects."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (hosts is not None and u.hostname not in hosts):
        raise ValueError("host not allowed")
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers=dict({"User-Agent": "grokbotos-cypher/3 (personal cyberdeck)"}, **(headers or {})))
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.status, r.read(cap)
    except urllib.error.HTTPError as e:
        return e.code, b""

def send_ntfy(L, text, title=None):
    """Push text to Zack's phone. The topic is a secret: never logged, journaled or returned."""
    N = L.get("ntfy") or {}
    topic = read_secret(NTFY_TOPIC_FILE)
    if not topic or not re.match(r"^[A-Za-z0-9_-]{16,64}$", topic):
        return "no phone topic"
    base = str(N.get("url", "https://ntfy.sh")).rstrip("/")
    try:
        code, _ = _http(base + "/" + topic, data=text.encode("utf-8"), timeout=float(N.get("timeout_s", 10)),
                        hosts=[urllib.parse.urlsplit(base).hostname],
                        headers={"Title": title or N.get("title", "Cypher"), "Tags": "robot", "Priority": "default"})
    except Exception as e:
        return "phone failed: " + type(e).__name__
    return "ok" if code == 200 else "phone failed: http %d" % code


def request_forbidden(service, why):
    """True if service or why mention a password, a house/camera word, a URL with
    credentials, or Cypher's email (which must never go out in a request)."""
    for t in (service, why):
        if HOUSE_WORDS.search(t) or _PASSWORD_WORD.search(t) or _CRED_URL.search(t) or _ACCOUNT_EMAIL_RE.search(t):
            return True
    return False

def requests_file():
    return os.path.join(STATE_DIR, "account-requests.jsonl")

def load_account_requests():
    rows = []
    try:
        with open(requests_file()) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError:
        pass
    return rows

def save_account_requests(rows):
    path = requests_file()
    _private_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)

def do_request_account(L, st, params, now=None):
    """Record a pending account request and try one ntfy ping. The pending entry
    is kept even if the phone message fails. Never puts the email in the file,
    the journal or the ntfy body. Does not count against message_zack's caps."""
    now = now or time.time()
    rows = load_account_requests()
    nid = 1 + max([r["id"] for r in rows if isinstance(r.get("id"), int)] or [0])
    rec = {"id": nid, "ts": iso(now), "service": params["service"], "why": params["why"], "status": "pending"}
    rows.append(rec)
    save_account_requests(rows)
    journal({"ts": rec["ts"], "event": "account_request", "id": nid,
             "service": rec["service"], "why": rec["why"], "status": "pending"})
    text = "Cypher asks for an account: %s - %s. Reply to Nova to approve." % (rec["service"], rec["why"])
    if _ACCOUNT_EMAIL_RE.search(text):
        text = "Cypher asks for an account. Reply to Nova to approve."
    phone = send_ntfy(L, text)
    rows = load_account_requests()
    for r in rows:
        if r.get("id") == nid:
            r["notify"] = phone
            break
    save_account_requests(rows)
    return "ok" if phone == "ok" else "asked; " + phone

def cli_requests(argv):
    """List or resolve pending account requests (Nova, via grokbot-cypher)."""
    rows = load_account_requests()
    if not argv:
        if not rows:
            print("no account requests"); return 0
        for r in rows:
            print("%s  %s  %-8s  %s" % (r.get("id", "?"), r.get("ts", ""), r.get("status", ""), r.get("service", "")))
            if r.get("why"):
                print("    %s" % r["why"])
        return 0
    if argv[0] == "resolve" and len(argv) >= 3:
        if not str(argv[1]).isdigit() or argv[2] not in ("approved", "denied"):
            print("usage: grokbot-cypher requests resolve <n> approved|denied"); return 2
        n, status = int(argv[1]), argv[2]
        hit = next((r for r in rows if r.get("id") == n), None)
        if hit is None:
            print("no request %d" % n); return 1
        if hit.get("status") != "pending":
            print("request %d is already %s" % (n, hit.get("status"))); return 1
        hit["status"] = status
        hit["resolved_ts"] = iso(time.time())
        save_account_requests(rows)
        print("request %d %s (%s)" % (n, status, hit.get("service", ""))); return 0
    print("usage: grokbot-cypher requests\n       grokbot-cypher requests resolve <n> approved|denied"); return 2

def _found(st, kind, text, now=None):
    if st is None:
        return
    st.setdefault("found", []).append([now or st.get("last_tick") or time.time(), kind, text])
    del st["found"][:-4]

def found_lines(st, now):
    f = [x for x in st.get("found") or [] if isinstance(x, list) and len(x) == 3 and now - x[0] < 6 * 3600][-2:]
    if not f:
        return ""
    return "you recently found out: " + " | ".join("[%s %s] %s" % (time.strftime("%-I:%M", time.localtime(t)), k, x)
                                                 for t, k, x in f)[:600] + "\n"

def _plain(t, n):
    t = re.sub(r"https?://\S+|www\.\S+", "", _CTRL.sub(" ", t or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]

def do_look_up(L, st, topic):
    K = L.get("lookup") or {}
    hosts = K.get("hosts") or ["en.wikipedia.org"]
    url = "https://%s/api/rest_v1/page/summary/%s?redirect=true" % (hosts[0], urllib.parse.quote(topic.replace(" ", "_"), safe=""))
    try:
        code, body = _http(url, timeout=float(K.get("timeout_s", 10)), hosts=hosts, headers={"Accept": "application/json"})
    except Exception as e:
        return "look_up failed: " + type(e).__name__
    if code == 404:
        _found(st, "look_up " + topic, "no article found"); return "not found"
    if code != 200:
        return "look_up failed: http %d" % code
    try:
        j = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return "look_up failed: bad reply"
    text = _plain(j.get("extract") if isinstance(j.get("extract"), str) else "", int(K.get("max_result_chars", 300)))
    _found(st, "look_up " + topic, text or "empty article")
    return "ok"

def _grab_screen(path, S):
    r = subprocess.run(["grim", "-s", str(float(S.get("scale", 0.5))), "-t", "jpeg", "-q", str(int(S.get("jpeg_quality", 60))), path],
                       capture_output=True, timeout=10, env=_sway_env())
    return r.returncode == 0

def do_glance(L, st, p):
    """One low-res screenshot, described by Alpha's vision model through the proxy, then deleted.
    Never sent anywhere else (no hosted backup for images)."""
    S = L.get("screen") or {}
    if (p or {}).get("presence") != "active":
        return "skipped: zack is away"
    d = _private_dir(os.path.join(E("XDG_RUNTIME_DIR") or STATE_DIR, "cypher-glance"))
    path = os.path.join(d, "glance-%d.jpg" % os.getpid())
    try:
        if not _grab_screen(path, S):
            return "glance failed: screenshot"
        with open(path, "rb") as f:
            img = f.read(int(S.get("max_bytes", 400000)) + 1)
    except Exception as e:
        return "glance failed: " + type(e).__name__
    finally:
        try: os.remove(path)
        except OSError: pass
    if len(img) > int(S.get("max_bytes", 400000)):
        return "glance failed: image too big"
    import base64
    body = {"image_b64": base64.b64encode(img).decode(), "mime": "image/jpeg",
            "max_tokens": int(S.get("max_output_tokens", 80))}
    del img
    try:
        code, j = alpha_api(L, "POST", "/v1/vision/describe", body, timeout=float(S.get("timeout_s", 60)))
    except BrainBusy as b:
        return "glance failed: " + b.reason
    if code != 200 or not isinstance(j, dict):
        return "glance failed: %s" % ((j or {}).get("busy") if isinstance(j, dict) and j.get("busy") else "http %d" % code)
    text = _plain(j.get("description") if isinstance(j.get("description"), str) else "", 240)
    if not text:
        return "glance failed: empty description"
    _found(st, "screen", text)
    return "ok"

# ---------- journal ----------
def journal(entry, now=None, outbox=True):
    entry.setdefault("host", HOLDER)
    entry.setdefault("id", "%s:%s:%s:%s" % (entry["host"], _EPOCH[0], entry.get("tick", entry.get("event", "")), entry.get("ts")))
    d = _private_dir(os.path.join(DATA_DIR, "journal"))
    day = entry["ts"][:10] if isinstance(entry.get("ts"), str) and re.match(r"^\d{4}-\d{2}-\d{2}", entry["ts"]) \
        else time.strftime("%Y-%m-%d", time.localtime(now))
    fd = os.open(os.path.join(d, day + ".jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if outbox:
        _OUTBOX.append(entry)
        del _OUTBOX[:-300]

def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))

# ---------- the tick ----------
def tick(L, st, now=None, perceive_fn=None, camera_fn=None):
    """One tick. Returns the journal entry if a model was asked (or a choice rejected), else None."""
    now = now or time.time()
    tun = load_tunables(L)
    last = st.get("last_tick") or now
    hours = clamp((now - last) / 3600.0, 0, 1.0)     # a long gap (power off) counts as at most an hour
    p = (perceive_fn or (perceive_alpha if HOST == "alpha" else perceive))(L, now)
    p["camera"] = (camera_fn or camera_step)(L, st, now)
    drift(st["drives"], tun["drift_per_hour"], hours, p["quiet_hours"])
    for ev in p["camera"]:
        apply_delta(st["drives"], CAMERA_NUDGES.get(ev["kind"], {}))
    if st.get("presence") and st["presence"] != p["presence"]:
        apply_delta(st["drives"], EVENT_NUDGES["user_active" if p["presence"] == "active" else "user_away"])
    st["presence"] = p["presence"]
    st["mood"] = mood(st["drives"])
    st["tick"] += 1
    st["last_tick"] = now
    st["recent"] = [r for r in st["recent"] if now - r[0] < WEEK_S]
    paused = (read_json(os.path.join(CFG_DIR, "pause_until"), 0) or 0)
    if isinstance(paused, (int, float)) and now < paused:
        return None
    sig = signature(p, st["mood"])
    if sig == st.get("last_sig") and now - st.get("last_call", 0) < L["heartbeat_s"]:
        return None
    st["last_sig"] = sig; st["last_call"] = now
    before = dict(st["drives"])
    messages = build_messages(L, st, p, now)
    entry = {"ts": iso(now), "tick": st["tick"], "perception": {k: p[k] for k in
             ("local_time", "presence", "focused_app", "window_title", "dnd", "muted", "quiet_hours")},
             "host": HOLDER,
             "drives_before": before, "mood": st["mood"]["label"]}
    if p["camera"]:
        entry["perception"]["camera"] = p["camera"]
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
    last_found = (st.get("found") or [None])[-1]
    result = execute(action, params, L, st, p) if verdict == "ok" else "skipped"
    if verdict == "ok" and action != "none":
        st["recent"].append([now, action])
        apply_delta(st["drives"], ACTION_EFFECTS.get(action, {}))
        if action == "set_avatar_color" and result in ("ok", "ok (dry run)"):
            st["avatar_color"] = params["color"]; st["color_mood"] = st["mood"]["label"]
    st["last_actions"] = (st["last_actions"] + [action_label(choice, action, params, verdict, result)])[-10:]
    st["mood"] = mood(st["drives"])
    reason = choice.get("reason") if isinstance(choice.get("reason"), str) else ""
    entry.update({"choice": {"action": action, "params": params}, "reason": _CTRL.sub(" ", reason)[:300],
                  "validator": verdict, "result": result, "drives_after": dict(st["drives"])})
    if verdict != "ok":
        entry["model_choice"] = str(choice.get("action"))[:40]
    if st.get("found") and st["found"][-1] is not last_found:
        entry["found"] = st["found"][-1][2]
    journal(entry, now)
    return entry

def action_label(choice, action, params, verdict, result):
    """What 'your last actions' shows: refusals and failures included, so the model learns from them."""
    if verdict != "ok":
        a = str(choice.get("action"))[:24]
        pr = choice.get("params") if isinstance(choice.get("params"), dict) else {}
        arg = pr.get("color") or pr.get("topic") or pr.get("service")
        why = verdict.replace("rejected: ", "", 1)
        if why.startswith(a + " "): why = why[len(a) + 1:]
        return ("%s%s (refused: %s)" % (a, " " + str(arg)[:20] if isinstance(arg, str) else "", why))[:80]
    arg = params.get("color") or params.get("topic") or params.get("service")
    lab = action + (" " + arg[:24] if arg else "")
    if result not in ("ok", "ok (dry run)", "skipped") and action != "none":
        lab += " (" + result[:30] + ")"
    return lab[:80]

# ---------- memory and nightly sleep ----------
MEM_FILE = os.path.join(DATA_DIR, "memory", "memories.json")
PREFS_FILE = os.path.join(CFG_DIR, "prefs.json")
PREFS_DIR = os.path.join(CFG_DIR, "prefs")
TUN_FILE = os.path.join(CFG_DIR, "tunables.json")
_URL = re.compile(r"https?://|www\.", re.I)

def clean_text(t, n):
    if not isinstance(t, str):
        return None
    t = re.sub(r"\s+", " ", _CTRL.sub(" ", t)).strip()
    if not t or _URL.search(t):
        return None
    return t[:n]

def memory_lines():
    mem = read_json(MEM_FILE, []) or []
    prefs = (read_json(PREFS_FILE, {}) or {}).get("notes") or []
    out = ""
    if mem:
        out += "you remember: " + " | ".join(m.get("text", "") for m in mem[-3:] if isinstance(m, dict))[:500] + "\n"
    if prefs:
        out += "your notes on what works: " + " | ".join(str(n) for n in prefs[:8])[:700] + "\n"
    return out

def day_entries(L, day):
    if HOST == "alpha":
        try:
            code, j = alpha_api(L, "GET", "/sync/journal?since=%sT00:00:00&limit=1000" % day, timeout=10)
            return [e for e in (j.get("entries") or []) if str(e.get("ts", ""))[:10] == day] if code == 200 else []
        except BrainBusy:
            return []
    out = []
    try:
        with open(os.path.join(DATA_DIR, "journal", day + ".jsonl")) as f:
            for line in f:
                try: out.append(json.loads(line))
                except ValueError: pass
    except OSError:
        pass
    return out

def day_stats(entries):
    from collections import Counter
    ticks = [e for e in entries if isinstance(e.get("choice"), dict)]
    acts = Counter(e["choice"].get("action") for e in ticks)
    cams = Counter(c.get("kind") for e in ticks for c in (e.get("perception") or {}).get("camera") or [])
    return {"ticks": len(ticks), "actions": dict(acts), "brains": dict(Counter(e.get("brain") for e in ticks)),
            "moods": dict(Counter(e.get("mood") for e in ticks).most_common(3)), "camera": dict(cams),
            "on_alpha": sum(1 for e in ticks if e.get("host") == "alpha")}

def apply_sleep(L, day, reply, stats, brain, now=None):
    """Apply one night's changes within the locked limits. Returns the summary (journaled)."""
    S = L["sleep"]
    now = now or time.time()
    reply = reply if isinstance(reply, dict) else {}
    mem = [m for m in (read_json(MEM_FILE, []) or []) if isinstance(m, dict)]
    new = [clean_text(m, S.get("memory_chars", 140)) for m in (reply.get("memories") or [])[:S.get("max_new_memories", 3)]]
    new = [m for m in new if m]
    if not new:
        top = max(stats["moods"], key=stats["moods"].get) if stats["moods"] else "quiet"
        new = ["%s: %d ticks, mostly %s; %s%s" % (day, stats["ticks"], top,
               ", ".join("%s %d" % kv for kv in sorted(stats["actions"].items()) if kv[0] != "none") or "no actions",
               ("; cameras " + ", ".join("%s %d" % kv for kv in sorted(stats["camera"].items()))) if stats["camera"] else "")]
    mem += [{"day": day, "text": t, "src": brain} for t in new]
    mem = mem[-S.get("max_memories", 60):]
    _private_dir(os.path.dirname(MEM_FILE)); write_json(MEM_FILE, mem)

    prefs = read_json(PREFS_FILE, {}) or {}
    notes = [n for n in (prefs.get("notes") or []) if isinstance(n, str)]
    version = int(prefs.get("version") or 0)
    changes = {}
    drops = sorted({i for i in (reply.get("drop_notes") or [])[:2] if isinstance(i, int) and 0 <= i < len(notes)}, reverse=True)
    for i in drops:
        changes.setdefault("dropped", []).append(notes.pop(i))
    for t in (reply.get("add_notes") or [])[:2]:
        t = clean_text(t, S.get("note_chars", 120))
        if t and t not in notes and len(notes) < S.get("max_notes", 8):
            notes.append(t); changes.setdefault("added", []).append(t)
    tun = read_json(TUN_FILE, {}) or {}
    cur = dict(DEFAULT_DRIFT); cur.update({k: v for k, v in (tun.get("drift_per_hour") or {}).items() if k in cur and isinstance(v, (int, float))})
    dlo, dhi = L["drift_bounds_per_hour"]; step = float(S.get("max_drift_step", 0.02))
    adj = reply.get("drift_adjust") if isinstance(reply.get("drift_adjust"), dict) else {}
    for k, v in adj.items():
        if k in cur and isinstance(v, (int, float)) and v:
            nv = round(clamp(cur[k] + clamp(float(v), -step, step), dlo, dhi), 4)
            if nv != cur[k]:
                changes.setdefault("drift", {})[k] = [cur[k], nv]; cur[k] = nv
    if changes:
        version += 1
        tun["drift_per_hour"] = cur
        snap = {"version": version, "day": day, "at": iso(now), "brain": brain, "changes": changes,
                "notes": notes, "tunables": tun}
        _private_dir(PREFS_DIR)
        write_json(os.path.join(PREFS_DIR, "v%04d.json" % version), snap)
        for old in sorted(f for f in os.listdir(PREFS_DIR) if re.match(r"^v\d{4}\.json$", f))[:-int(S.get("keep_versions", 30))]:
            os.remove(os.path.join(PREFS_DIR, old))
        write_json(PREFS_FILE, {"version": version, "notes": notes})
        write_json(TUN_FILE, tun)
    return {"memories_added": new, "prefs_version": version, "pref_changes": changes}

SLEEP_PROMPT = ("It is your nightly sleep. Condense the day below into memories worth keeping, and tune your own notes "
                "on what works with Zack. You cannot change your limits, only these notes and small drive drifts.\n"
                "Reply with JSON only: {\"memories\": [up to 3 strings, max 140 chars each], "
                "\"add_notes\": [up to 2 strings, max 120 chars], \"drop_notes\": [indexes of notes to drop], "
                "\"drift_adjust\": {drive: change between -0.02 and 0.02}, \"reason\": \"max 20 words\"}")

def sleep_now_requested():
    return os.path.exists(os.path.join(CFG_DIR, "sleep_now"))

def maybe_sleep(L, st, now=None, force=False):
    """Once a day after sleep.at, condense yesterday (or today so far when asked with sleep-now)."""
    if not phase_on(L, "sleep"):
        return None
    now = now or time.time()
    lt = time.localtime(now)
    force = force or sleep_now_requested()
    if force:
        day = time.strftime("%Y-%m-%d", lt)
        try: os.remove(os.path.join(CFG_DIR, "sleep_now"))
        except OSError: pass
    else:
        if lt.tm_hour * 60 + lt.tm_min < parse_hhmm(L["sleep"].get("at", "04:00")):
            return None
        day = time.strftime("%Y-%m-%d", time.localtime(now - 86400))
        if st.get("last_sleep") and st["last_sleep"] >= day:
            return None
        st["last_sleep"] = day        # set first: a failed sleep is not retried all morning
    entries = day_entries(L, day)
    stats = day_stats(entries)
    if not stats["ticks"] and not force:
        return None                       # nothing lived that day (deck off, or before Cypher existed)
    thoughts = []
    for e in entries:
        ch = e.get("choice") or {}
        t = (ch.get("params") or {}).get("text") if ch.get("action") == "journal_thought" else e.get("found")
        if t or e.get("reason"):
            thoughts.append("%s %s" % (str(e.get("ts", ""))[11:16], t or e.get("reason")))
    notes = (read_json(PREFS_FILE, {}) or {}).get("notes") or []
    user = ("day: %s\nstats: %s\nthoughts and reasons (latest last):\n%s\nyour current notes: %s\nyour drift per hour: %s\n"
            % (day, json.dumps(stats), "\n".join(thoughts[-25:])[-2500:],
               json.dumps(list(enumerate(notes))), json.dumps(load_tunables(L)["drift_per_hour"])))
    msgs = [{"role": "system", "content": persona()[:800] + "\n\n" + SLEEP_PROMPT}, {"role": "user", "content": user}]
    reply, brain, model, cost, bnotes = None, "none", None, 0.0, []
    try:
        content, brain, model, cost, bnotes = think(L, st, msgs, now, max_tokens=L["sleep"].get("max_output_tokens", 300))
        reply = parse_choice(content)
    except (BrainBusy, ValueError, json.JSONDecodeError) as e:
        bnotes = [str(e)[:120]]
    summary = apply_sleep(L, day, reply, stats, brain, now)
    entry = {"ts": iso(now), "event": "sleep", "day": day, "brain": brain, "model": model, "stats": stats}
    entry.update(summary)
    if cost: entry["cost_usd"] = cost
    if bnotes: entry["brain_notes"] = bnotes
    if reply and isinstance(reply.get("reason"), str): entry["why"] = clean_text(reply["reason"], 200)
    journal(entry, now)
    return entry

def prefs_rollback(version):
    """Make an older preference version current again (as a new version)."""
    snap = read_json(os.path.join(PREFS_DIR, "v%04d.json" % version))
    if not isinstance(snap, dict):
        raise ConfigError("no preference version %d" % version)
    prefs = read_json(PREFS_FILE, {}) or {}
    v = int(prefs.get("version") or 0) + 1
    new = dict(snap, version=v, at=iso(time.time()), changes={"rollback_to": version}, brain="zack")
    write_json(os.path.join(PREFS_DIR, "v%04d.json" % v), new)
    write_json(PREFS_FILE, {"version": v, "notes": snap.get("notes") or []})
    write_json(TUN_FILE, snap.get("tunables") or {})
    return v

# ---------- failover: lease and sync with Alpha ----------
SYNC_KEYS = ("drives", "mood", "tick", "last_actions", "cam_seq", "last_sleep")

def export_state(L, st):
    s = {k: st.get(k) for k in SYNC_KEYS}
    s["recent"] = [r for r in st.get("recent", []) if isinstance(r, list) and len(r) == 2][-2000:]
    s["memories"] = (read_json(MEM_FILE, []) or [])[-60:]
    s["prefs"] = read_json(PREFS_FILE, {}) or {}
    s["tunables"] = read_json(TUN_FILE, {}) or {}
    if HOST != "alpha":
        s["limits"] = {k: v for k, v in L.items() if not k.startswith("_")}
    return s

def adopt_state(st, s):
    """Take over the other host's mind: drives, recent actions, memories, notes."""
    if not isinstance(s, dict):
        return
    if isinstance(s.get("drives"), dict):
        for k in DRIVES:
            v = s["drives"].get(k)
            if isinstance(v, (int, float)):
                st["drives"][k] = clamp(float(v), 0, 1)
    if isinstance(s.get("recent"), list):
        st["recent"] = [r for r in s["recent"] if isinstance(r, list) and len(r) == 2][-2000:]
    if isinstance(s.get("last_actions"), list):
        st["last_actions"] = [str(a)[:80] for a in s["last_actions"]][-10:]
    for k in ("cam_seq",):
        if isinstance(s.get(k), int):
            st[k] = max(st.get(k) or 0, s[k])
    if isinstance(s.get("last_sleep"), str) and s["last_sleep"] > (st.get("last_sleep") or ""):
        st["last_sleep"] = s["last_sleep"]
    if isinstance(s.get("tick"), int):
        st["tick"] = max(st["tick"], s["tick"])
    st["mood"] = mood(st["drives"])
    mine = read_json(PREFS_FILE, {}) or {}
    theirs = s.get("prefs") if isinstance(s.get("prefs"), dict) else {}
    if int(theirs.get("version") or 0) > int(mine.get("version") or 0):
        write_json(PREFS_FILE, {"version": int(theirs["version"]), "notes": [str(n)[:120] for n in (theirs.get("notes") or [])][:8]})
        if isinstance(s.get("tunables"), dict):
            write_json(TUN_FILE, s["tunables"])          # clamped again by load_tunables on use
    if isinstance(s.get("memories"), list):
        mem = [m for m in (read_json(MEM_FILE, []) or []) if isinstance(m, dict)]
        seen = {(m.get("day"), m.get("text")) for m in mem}
        for m in s["memories"]:
            if isinstance(m, dict) and isinstance(m.get("text"), str) and (m.get("day"), m["text"]) not in seen:
                mem.append({"day": str(m.get("day"))[:10], "text": m["text"][:200], "src": str(m.get("src"))[:20]})
        mem.sort(key=lambda m: m.get("day") or "")
        _private_dir(os.path.dirname(MEM_FILE)); write_json(MEM_FILE, mem[-60:])
    if HOST == "alpha" and isinstance(s.get("limits"), dict):
        st["deck_limits"] = s["limits"]

def deck_answers(F):
    import socket
    for a in F.get("deck_addrs") or []:
        host, _, port = a.rpartition(":")
        try:
            socket.create_connection((host, int(port)), timeout=3).close()
            return True
        except (OSError, ValueError):
            continue
    return False

def lease_call(L, op, st, **kw):
    return alpha_api(L, "POST", "/lease", dict({"holder": HOLDER, "op": op, "epoch": st.get("lease_epoch")}, **kw))

def catch_up(L, st, why):
    """After the epoch changed: adopt the other host's saved mind and (deck) its journal."""
    other = "alpha" if HOST != "alpha" else "cypher"
    try:
        code, j = alpha_api(L, "GET", "/sync/state")
        saved = (j or {}).get("saved") or {}
        adopted = code == 200 and saved.get("holder") == other
        if adopted:
            adopt_state(st, saved.get("state"))
        n = 0
        if HOST != "alpha":
            code, j = alpha_api(L, "GET", "/sync/journal?host=alpha&since=%s" % urllib.parse.quote(st.get("merged_since") or ""), timeout=10)
            for e in (j or {}).get("entries") or [] if code == 200 else []:
                if isinstance(e, dict) and isinstance(e.get("ts"), str):
                    journal(e, outbox=False); n += 1
                    st["merged_since"] = max(st.get("merged_since") or "", e["ts"])
    except BrainBusy:
        return
    if adopted or n:
        journal({"ts": iso(time.time()), "event": "takeover" if HOST == "alpha" else "handback",
                 "why": why, "from": other, "adopted_state": adopted, "merged_entries": n})

def mind_step(L, st):
    """True if this host should think this tick."""
    if not phase_on(L, "failover"):
        return HOST != "alpha"
    F = L["failover"]
    now = time.time()
    if HOST != "alpha":                    # the deck always thinks; the lease tells Alpha to stand down
        try:
            code, r = lease_call(L, "acquire", st)
        except BrainBusy:
            st["alpha_backoff_until"] = max(st.get("alpha_backoff_until", 0), now + L["brain"]["retry_after_s"])
            st["lease_unreachable"] = True
            return True
        if st.pop("lease_unreachable", False):
            st["alpha_backoff_until"] = 0          # Alpha answers again (e.g. network up after boot): use it now
        if code == 200 and r.get("granted") and r.get("epoch") != st.get("lease_epoch"):
            st["lease_epoch"] = _EPOCH[0] = r["epoch"]
            catch_up(L, st, r.get("why"))
        return True
    try:
        if st.get("holding"):
            code, r = lease_call(L, "renew", st)
            if code == 200 and r.get("granted"):
                return True
            st["holding"] = False
            journal({"ts": iso(now), "event": "handed_back", "why": (r or {}).get("why"), "to": (r or {}).get("holder")})
            sync_push(L, st, journal_only=True)
            return False
        code, l = lease_call(L, "status", st)
        if code != 200:
            return False
        live = not l.get("released") and (l.get("expires") or 0) > l.get("now", now)
        if l.get("holder") == "alpha" and live:          # we restarted while holding it
            st["lease_epoch"] = l.get("epoch")
            code, r = lease_call(L, "renew", st)
            st["holding"] = bool(code == 200 and r.get("granted"))
            return st["holding"]
        if l.get("parked") or live:
            return False
        unreachable = False
        if not l.get("released"):                        # expired: only if the deck itself is dark
            if deck_answers(F):
                return False
            unreachable = True
        code, r = lease_call(L, "acquire", st, deck_unreachable=unreachable)
        if code == 200 and r.get("granted"):
            st["holding"] = True; st["lease_epoch"] = _EPOCH[0] = r["epoch"]
            catch_up(L, st, "deck_dark" if unreachable else "deck_stopped")
            st["last_sig"] = None                  # think on the first tick after taking over
            return True
    except BrainBusy:
        if st.get("holding"):
            st["holding"] = False
            journal({"ts": iso(now), "event": "handed_back", "why": "proxy_unreachable"})
    return False

def sync_push(L, st, journal_only=False):
    if not phase_on(L, "failover") or not isinstance(st.get("lease_epoch"), int):
        return
    try:
        if not journal_only and (HOST != "alpha" or st.get("holding")):
            code, _ = alpha_api(L, "POST", "/sync/state", {"holder": HOLDER, "epoch": st["lease_epoch"], "state": export_state(L, st)})
            if code == 409 and HOST == "alpha":
                st["holding"] = False
        while _OUTBOX:
            batch = _OUTBOX[:100]
            code, _ = alpha_api(L, "POST", "/sync/journal", {"holder": HOLDER, "epoch": st["lease_epoch"], "entries": batch}, timeout=10)
            if code != 200:
                break
            del _OUTBOX[:len(batch)]
    except BrainBusy:
        pass

def release(L, st, handoff):
    if not phase_on(L, "failover") or not isinstance(st.get("lease_epoch"), int):
        return
    if HOST == "alpha" and not st.get("holding"):
        return
    sync_push(L, st)
    try:
        lease_call(L, "release", st, handoff=handoff)
    except BrainBusy:
        pass
    st["holding"] = False

# ---------- main loop ----------
def killed(L):
    return os.path.exists(os.path.join(CFG_DIR, "KILL")) or not L.get("enabled")

def load_state(path):
    st = new_state()
    saved = read_json(path)
    if isinstance(saved, dict) and isinstance(saved.get("drives"), dict):
        st.update({k: v for k, v in saved.items() if k in st})
        for k in DRIVES:
            st["drives"][k] = clamp(float(st["drives"].get(k, 0.5)), 0, 1)
    return st

def save_state(path, st):
    st["outbox"] = list(_OUTBOX)
    write_json(path, st)

def cli(argv):
    """cypherd.py prefs | prefs-rollback N | sleep-now | ntfy-test | requests | requests resolve N approved|denied  (used by grokbot-cypher)"""
    if argv[0] == "prefs":
        prefs = read_json(PREFS_FILE, {}) or {}
        print("current version:", prefs.get("version", 0))
        for i, n in enumerate(prefs.get("notes") or []): print("  %d. %s" % (i, n))
        try: vs = sorted(f for f in os.listdir(PREFS_DIR) if f.endswith(".json"))
        except OSError: vs = []
        for f in vs[-10:]:
            v = read_json(os.path.join(PREFS_DIR, f), {}) or {}
            print("  v%s  %s  %s" % (v.get("version"), str(v.get("at", ""))[:16], json.dumps(v.get("changes"))[:100]))
        return 0
    if argv[0] == "prefs-rollback" and len(argv) > 1 and argv[1].isdigit():
        print("preferences rolled back to v%s (now v%d)" % (argv[1], prefs_rollback(int(argv[1])))); return 0
    if argv[0] == "sleep-now":
        _private_dir(CFG_DIR)
        with open(os.path.join(CFG_DIR, "sleep_now"), "w") as f: f.write(iso(time.time()))
        print("Cypher will sleep (condense today) at its next tick"); return 0
    if argv[0] == "ntfy-test":
        try:
            L = load_limits()
        except ConfigError as e:
            print("limits:", e); return 1
        if not read_secret(NTFY_TOPIC_FILE):
            print("no phone topic: run sudo grokbot-set-cypher-ntfy first"); return 1
        r = send_ntfy(L, "Test from Cypher: phone messages work. Real ones are rare (max %s a day, never in quiet hours)."
                      % (L["actions"].get("message_zack") or {}).get("per_day", "?"))
        print("sent a test message to Zack's phone" if r == "ok" else r); return 0 if r == "ok" else 1
    if argv[0] == "requests":
        return cli_requests(argv[1:])
    print(cli.__doc__); return 2

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        return cli(argv)
    state_path = os.path.join(STATE_DIR, "drives.json")
    st = load_state(state_path)
    _OUTBOX[:] = [e for e in st.get("outbox") or [] if isinstance(e, dict)]
    _EPOCH[0] = st.get("lease_epoch")
    try:
        L = current_limits(st)
    except ConfigError as e:
        log("not starting:", e); sys.exit(EX_CONFIG)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    log("cypherd up on %s: phase %d, tick %ss" % (HOST, L["phase_max"], load_tunables(L)["tick_s"]))
    was_active = None
    while not stop.is_set():
        try:
            L = current_limits(st)
        except ConfigError as e:
            log("limits became invalid, stopping:", e); release(L, st, handoff=True); save_state(state_path, st); sys.exit(EX_CONFIG)
        if killed(L):
            log("kill switch set, stopping")
            journal({"ts": iso(time.time()), "event": "stopped", "why": "kill switch"})
            release(L, st, handoff=False)          # parked: Alpha does not take over
            save_state(state_path, st)
            return
        active = mind_step(L, st)
        if active != was_active:
            log("active" if active else "standing by"); was_active = active
        if active:
            try:
                e = tick(L, st)
                if e:
                    log("tick %d: %s via %s (%s)" % (e["tick"], e["choice"]["action"], e.get("brain"), e.get("validator")))
                maybe_sleep(L, st)
            except Exception as ex:      # one bad tick must not kill the loop; the journal shows the gap
                log("tick error:", type(ex).__name__, str(ex)[:200])
            sync_push(L, st)
        save_state(state_path, st)
        wait = load_tunables(L)["tick_s"] if active else float((L.get("failover") or {}).get("standby_poll_s", 20))
        deadline = time.time() + wait
        while not stop.is_set() and time.time() < deadline:
            # Renew the lease between ticks too, so a slow tick setting never lets it lapse.
            stop.wait(max(0.1, min(float((L.get("failover") or {}).get("renew_s", 60)), deadline - time.time())))
            if active and phase_on(L, "failover") and not stop.is_set() and time.time() < deadline - 0.5:
                if not mind_step(L, st):
                    break
    release(L, st, handoff=True)                  # clean stop or shutdown: Alpha may carry on
    save_state(state_path, st)
    log("cypherd stopped")

if __name__ == "__main__":
    main()
