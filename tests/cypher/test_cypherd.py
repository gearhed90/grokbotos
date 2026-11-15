#!/usr/bin/env python3
"""Unit and end-to-end tests for cypherd (Cypher's autonomy loop) and the
grokbot-cypher CLI. Fake brains on localhost; no display, root or network."""
import importlib.util, json, os, socket, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "build_files", "rpi5", "cypher")
NOVA = os.path.join(ROOT, "build_files", "rpi5", "nova")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))

T = tempfile.mkdtemp()
TOKEN = "k" * 40; XKEY = "x" * 40
for n, v in (("token", TOKEN), ("xai", XKEY)):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
limits_src = json.load(open(os.path.join(SRC, "cypher-limits.json")))

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

# ---- fake brains: the Alpha proxy and the hosted API ----
BR = {"alpha": {"code": 200, "reply": '{"action":"journal_thought","params":{"text":"Grid quiet."},"reason":"nothing to do"}', "seen": []},
      "hosted": {"code": 200, "reply": '{"action":"none","reason":"idle"}', "seen": []}}
class Fake(BaseHTTPRequestHandler):
    which = None
    def log_message(self, *a): pass
    def do_POST(self):
        b = BR[self.which]
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        b["seen"].append({"auth": self.headers.get("Authorization"), "body": body, "path": self.path})
        if b["code"] != 200:
            out = json.dumps({"busy": b.get("busy", "camera_busy")}).encode()
        else:
            out = json.dumps({"model": "fake", "choices": [{"message": {"content": b["reply"]}}],
                              "usage": {"prompt_tokens": 800, "completion_tokens": 40}}).encode()
        self.send_response(b["code"]); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
ports = {}
for w in ("alpha", "hosted"):
    H = type("H_" + w, (Fake,), {"which": w}); ports[w] = free_port()
    s = ThreadingHTTPServer(("127.0.0.1", ports[w]), H); threading.Thread(target=s.serve_forever, daemon=True).start()

def write_limits(**over):
    L = json.loads(json.dumps(limits_src))
    L["brain"]["primary_url"] = "http://127.0.0.1:%d" % ports["alpha"]
    L["brain"]["hosted_backup"]["url"] = "http://127.0.0.1:%d/v1" % ports["hosted"]
    for k, v in over.items():
        if k == "hosted_backup": L["brain"]["hosted_backup"].update(v)
        else: L[k] = v
    p = os.path.join(T, "limits.json")
    with open(p, "w") as f: json.dump(L, f)
    return p

os.environ.update(CYPHER_LIMITS=write_limits(), CYPHER_LIMITS_INSECURE_OK="1", CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"),
                  CYPHER_XAI_KEY_FILE=os.path.join(T, "xai"), CYPHER_CONFIG_DIR=os.path.join(T, "cfg"),
                  CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_DATA_DIR=os.path.join(T, "data"),
                  CYPHER_PERSONA=os.path.join(SRC, "persona.md"), CYPHER_DRY_RUN="1", TZ="America/New_York")
spec = importlib.util.spec_from_file_location("cypherd", os.path.join(SRC, "cypherd.py"))
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

# ---- shipped limits ----
shipped = C.load_limits(os.path.join(SRC, "cypher-limits.json"))
check("shipped limits load", shipped["phase_max"] == 1 and shipped["tick_s"] == 45)
check("v1 actions are exactly none/journal/note/avatar", sorted(C.allowed_actions(shipped)) == ["journal_thought", "none", "set_avatar_color", "show_note"])
check("quiet hours 11 PM to 6 AM, off Friday and Saturday nights",
      shipped["quiet_hours"] == {"default": ["23:00", "06:00"], "nights": {"fri": None, "sat": None}})
check("hosted backup capped at $0.50/day", shipped["brain"]["hosted_backup"]["daily_budget_usd"] == 0.5)
check("primary brain is the Alpha proxy on 8090", shipped["brain"]["primary_url"] == "http://192.168.12.126:8090")
sys.path.insert(0, NOVA)
import avatar_shapes
check("avatar colors match novad's list", shipped["avatar_colors"] == avatar_shapes.COLOR_IDS)
bad = os.path.join(T, "bad.json")
with open(bad, "w") as f: json.dump({"enabled": True}, f)
try: C.load_limits(bad); check("incomplete limits refused", False)
except C.ConfigError: check("incomplete limits refused", True)
try: C.load_limits(os.path.join(T, "missing.json")); check("missing limits refused", False)
except C.ConfigError: check("missing limits refused", True)
os.environ.pop("CYPHER_LIMITS_INSECURE_OK"); C.INSECURE_OK = False
if os.getuid() != 0:
    try: C.load_limits(); check("limits not owned by root refused", False)
    except C.ConfigError: check("limits not owned by root refused", True)
    check("secret not owned by root refused", C.read_secret(os.path.join(T, "token")) is None)
C.INSECURE_OK = True; os.environ["CYPHER_LIMITS_INSECURE_OK"] = "1"
L = C.load_limits()

# ---- tunables are clamped to the locked bounds ----
os.makedirs(os.path.join(T, "cfg"), exist_ok=True)
with open(os.path.join(T, "cfg", "tunables.json"), "w") as f:
    json.dump({"tick_s": 1, "drift_per_hour": {"boredom": 5, "energy": -9, "bogus": 1}}, f)
tun = C.load_tunables(L)
check("tick_s clamped to 30", tun["tick_s"] == 30)
check("drift clamped to +/-0.2", tun["drift_per_hour"]["boredom"] == 0.2 and tun["drift_per_hour"]["energy"] == -0.2)
check("unknown drive ignored", "bogus" not in tun["drift_per_hour"])
os.remove(os.path.join(T, "cfg", "tunables.json"))

# ---- drives and mood ----
d = {"energy": 0.5, "curiosity": 0.5, "social": 0.5, "boredom": 0.5, "focus": 0.5}
C.drift(d, C.DEFAULT_DRIFT, 1.0, quiet=False)
check("an hour of drift moves boredom up, energy down", d["boredom"] > 0.5 and d["energy"] < 0.5, d)
C.drift(d, C.DEFAULT_DRIFT, 1.0, quiet=True)
check("quiet hours restore energy", d["energy"] > 0.47, d)
C.apply_delta(d, {"boredom": 9, "social": -9})
check("drives stay inside 0..1", d["boredom"] == 1.0 and d["social"] == 0.0)
check("mood: high boredom -> restless", C.mood({"energy": .6, "curiosity": .3, "social": .3, "boredom": .8, "focus": .4})["label"] == "restless")
check("mood: low energy -> drained", C.mood({"energy": .1, "curiosity": .9, "social": .3, "boredom": .8, "focus": .4})["label"] == "drained")

# ---- quiet hours: weekdays only (nights keyed by the day they start) ----
def at(h, m=0, day=15):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))    # Nov 15 2026 is a Sunday
Q = lambda day, h, m=0: C.in_quiet_hours(L, at(h, m, day))
check("Mon 23:30 quiet", Q(16, 23, 30))
check("Tue 05:59 quiet (Monday night)", Q(17, 5, 59))
check("Tue 06:00 not quiet", not Q(17, 6, 0))
check("Mon 14:00 not quiet", not Q(16, 14))
check("Fri 05:00 quiet (Thursday night)", Q(20, 5, 0))
check("Fri 22:59 not quiet", not Q(20, 22, 59))
check("Fri 23:30 not quiet (Friday night off)", not Q(20, 23, 30))
check("Sat 03:00 not quiet (Friday night off)", not Q(21, 3, 0))
check("Sat 23:30 not quiet (Saturday night off)", not Q(21, 23, 30))
check("Sun 05:59 not quiet (Saturday night off)", not Q(22, 5, 59))
check("Sun 23:30 quiet (Sunday night is a school night)", Q(22, 23, 30))
check("Mon 05:59 quiet (Sunday night)", Q(23, 5, 59))
Llist = dict(L, quiet_hours=["23:00", "06:00"]); Llist.pop("_quiet_nights", None)
check("plain list form still means every night", C.in_quiet_hours(Llist, at(23, 30, 20)))
for badq in ({"default": ["25:00", "06:00"]}, {"nights": {"funday": None}}, "23-06", {"default": ["23:00"]}):
    try: C.quiet_nights(badq); check("bad schedule refused: %r" % (badq,), False)
    except (C.ConfigError, ValueError): check("bad schedule refused: %r" % (badq,), True)

# ---- reply parsing ----
check("plain JSON parses", C.parse_choice('{"action":"none"}')["action"] == "none")
check("fenced JSON parses", C.parse_choice('```json\n{"action":"none","reason":"x"}\n```')["reason"] == "x")
check("JSON after chatter parses", C.parse_choice('Sure. {"action":"none"} done')["action"] == "none")
for junk in ("no json here", "[1,2]", None):
    try: C.parse_choice(junk); check("junk refused: %r" % (junk,), False)
    except (ValueError, json.JSONDecodeError): check("junk refused: %r" % (junk,), True)

# ---- validator ----
P = {"presence": "active", "dnd": False, "muted": False, "quiet_hours": False}
st = C.new_state(); now = at(14)
V = lambda ch, p=P: C.validate(L, st, p, ch, now)
check("none ok", V({"action": "none"})[2] == "ok")
check("unknown action -> none", V({"action": "rm_rf"})[:1] == ("none",) and "unknown" in V({"action": "rm_rf"})[2])
check("phase-2 action refused", "unknown" in V({"action": "message_zack", "params": {"text": "hi"}})[2])
L2 = json.loads(json.dumps(L)); L2["actions"]["message_zack"] = {"phase": 3}
check("action above phase_max refused", "not unlocked" in C.validate(L2, st, P, {"action": "message_zack"}, now)[2])
a, pr, v = V({"action": "journal_thought", "params": {"text": "  line\x00one\n two  "}})
check("journal text cleaned", v == "ok" and pr["text"] == "line one two", pr)
check("journal text over 280 refused", "over" in V({"action": "journal_thought", "params": {"text": "x" * 281}})[2])
check("journal without text refused", "needs text" in V({"action": "journal_thought", "params": {}})[2])
check("note ok when active", V({"action": "show_note", "params": {"text": "yo"}})[2] == "ok")
check("note refused when muted", "muted" in V({"action": "show_note", "params": {"text": "yo"}}, dict(P, muted=True))[2])
check("note refused in DND", "disturb" in V({"action": "show_note", "params": {"text": "yo"}}, dict(P, dnd=True))[2])
check("note refused in quiet hours", "quiet" in V({"action": "show_note", "params": {"text": "yo"}}, dict(P, quiet_hours=True))[2])
check("note refused when away", "away" in V({"action": "show_note", "params": {"text": "yo"}}, dict(P, presence="locked"))[2])
check("note over 120 refused", "over" in V({"action": "show_note", "params": {"text": "x" * 121}})[2])
st["recent"] = [[now - 60 * i, "show_note"] for i in range(3)]
check("4th note in an hour refused", "hourly cap" in V({"action": "show_note", "params": {"text": "yo"}})[2])
st["recent"] = [[now - 3700 - 60 * i, "show_note"] for i in range(12)]
check("13th note in a day refused", "daily cap" in V({"action": "show_note", "params": {"text": "yo"}})[2])
st["recent"] = []
check("avatar color ok", V({"action": "set_avatar_color", "params": {"color": "purple"}})[:2] == ("set_avatar_color", {"color": "purple"}))
check("avatar color not in list refused", "not allowed" in V({"action": "set_avatar_color", "params": {"color": "#fff"}})[2])
check("params not a dict handled", "needs text" in V({"action": "journal_thought", "params": "hi"})[2])

# ---- end-to-end ticks with fake brains ----
def fake_perceive(presence="active", app="files", hour=14):
    return lambda L, now: {"local_time": "Sun 2:00 PM", "hour": hour, "quiet_hours": False, "presence": presence,
                           "focused_app": app, "window_title": "tank notes", "dnd": False, "muted": False}
st = C.new_state(); t0 = at(14)
e = C.tick(L, st, t0, fake_perceive())
check("tick asks Alpha first", e["brain"] == "alpha" and e["choice"]["action"] == "journal_thought", e)
check("journal line written", os.path.exists(os.path.join(T, "data", "journal", "2026-11-15.jsonl")))
seen = BR["alpha"]["seen"][-1]
check("Alpha call carries the token header", seen["auth"] == "Bearer " + TOKEN)
check("Alpha call is text-only, small", all(isinstance(m["content"], str) for m in seen["body"]["messages"])
      and seen["body"]["max_tokens"] == 150 and sum(len(m["content"]) for m in seen["body"]["messages"]) < 6000)
check("prompt carries perception and manifest", "tank notes" in seen["body"]["messages"][1]["content"]
      and "set_avatar_color" in seen["body"]["messages"][0]["content"])
check("drive effect applied", e["drives_after"]["boredom"] < e["drives_before"]["boredom"])
e2 = C.tick(L, st, t0 + 45, fake_perceive())
check("nothing changed -> gated, no model call", e2 is None and len(BR["alpha"]["seen"]) == 1)
e3 = C.tick(L, st, t0 + 90, fake_perceive(app="firefox"))
check("focus change -> model call", e3 is not None and len(BR["alpha"]["seen"]) == 2)
e4 = C.tick(L, st, t0 + 90 + 601, fake_perceive(app="firefox"))
check("heartbeat after 10 min -> model call", e4 is not None)
# Alpha busy with cameras -> hosted backup, cost counted
BR["alpha"]["code"] = 503; BR["alpha"]["busy"] = "camera_busy"
e5 = C.tick(L, st, t0 + 2000, fake_perceive(app="files"))
check("camera busy -> hosted backup", e5["brain"] == "hosted" and "alpha_camera_busy" in e5["brain_notes"], e5)
check("backup cost recorded", e5["cost_usd"] > 0 and st["budget"]["usd"] == e5["cost_usd"])
check("hosted call uses the xAI key, never the proxy token", BR["hosted"]["seen"][-1]["auth"] == "Bearer " + XKEY)
check("camera busy does not back Alpha off", st["alpha_backoff_until"] == 0)
# Gaming -> backoff for 5 minutes
BR["alpha"]["busy"] = "gaming"; n_alpha = len(BR["alpha"]["seen"])
C.tick(L, st, t0 + 3000, fake_perceive(app="steam"))
check("gaming -> Alpha backs off 300 s", st["alpha_backoff_until"] == t0 + 3000 + 300)
C.tick(L, st, t0 + 3100, fake_perceive(app="game"))
check("during backoff Alpha is not called", len(BR["alpha"]["seen"]) == n_alpha + 1)
# Budget used up -> no brain -> none
st["budget"]["usd"] = 0.4999
BR["alpha"]["code"] = 503; BR["alpha"]["busy"] = "camera_busy"
e6 = C.tick(L, st, t0 + 3500, fake_perceive(app="files"))
check("budget used up -> tick is none", e6["brain"] == "none" and "backup_budget_used" in e6["reason"], e6)
# Backup disabled
os.environ["CYPHER_LIMITS"] = write_limits(hosted_backup={"enabled": False}); Loff = C.load_limits()
e7 = C.tick(Loff, st, t0 + 4000, fake_perceive(app="x"))
check("backup off + Alpha busy -> none", e7["brain"] == "none" and "backup_off" in e7["reason"], e7)
# Model proposes something forbidden -> rejected and journaled
BR["alpha"]["code"] = 200; BR["alpha"]["reply"] = '{"action":"unlock_door","params":{},"reason":"why not"}'
st["alpha_backoff_until"] = 0
e8 = C.tick(Loff, st, t0 + 4100, fake_perceive(app="y"))
check("forbidden action rejected -> none", e8["choice"]["action"] == "none" and e8["validator"].startswith("rejected") and e8["model_choice"] == "unlock_door", e8)
BR["alpha"]["reply"] = "I think I will journal"
e9 = C.tick(Loff, st, t0 + 4200, fake_perceive(app="z"))
check("unparseable reply -> none", "unparseable" in e9["validator"])
# Pause
with open(os.path.join(T, "cfg", "pause_until"), "w") as f: f.write(str(t0 + 99999))
check("paused -> no model call", C.tick(Loff, st, t0 + 4300, fake_perceive(app="paused")) is None)
os.remove(os.path.join(T, "cfg", "pause_until"))
# Secrets never in the journal
J = open(os.path.join(T, "data", "journal", "2026-11-15.jsonl")).read()
check("journal never contains a token or key", TOKEN not in J and XKEY not in J)
check("journal lines are valid JSON", all(json.loads(l) for l in J.splitlines()))
check("journal file is private (0600)", oct(os.stat(os.path.join(T, "data", "journal", "2026-11-15.jsonl")).st_mode & 0o777) == "0o600")

# ---- the daemon: kill switch and bad limits ----
env = dict(os.environ, CYPHER_LIMITS=write_limits())
os.makedirs(os.path.join(T, "cfg"), exist_ok=True)
open(os.path.join(T, "cfg", "KILL"), "w").close()
r = subprocess.run([sys.executable, os.path.join(SRC, "cypherd.py")], env=env, capture_output=True, text=True, timeout=20)
check("KILL file -> cypherd exits 0 at once", r.returncode == 0 and "kill switch" in r.stderr, r.stderr)
os.remove(os.path.join(T, "cfg", "KILL"))
r = subprocess.run([sys.executable, os.path.join(SRC, "cypherd.py")], env=dict(env, CYPHER_LIMITS=bad), capture_output=True, text=True, timeout=20)
check("bad limits -> exit 78 (systemd will not restart)", r.returncode == 78, r.returncode)
env_dis = dict(env, CYPHER_LIMITS=write_limits(enabled=False))
r = subprocess.run([sys.executable, os.path.join(SRC, "cypherd.py")], env=env_dis, capture_output=True, text=True, timeout=20)
check("enabled:false in limits -> stops", r.returncode == 0 and "kill switch" in r.stderr)
# SIGTERM ends a running loop cleanly and saves state
pr = subprocess.Popen([sys.executable, os.path.join(SRC, "cypherd.py")], env=dict(env, CYPHER_LIMITS=write_limits()),
                      stderr=subprocess.PIPE, text=True)
time.sleep(2.5); pr.terminate(); err = pr.communicate(timeout=10)[1]
check("SIGTERM -> clean stop", pr.returncode == 0 and "cypherd stopped" in err, err[-300:])
check("state saved", os.path.exists(os.path.join(T, "state", "drives.json")))

# ---- CLI ----
cli = [sys.executable, os.path.join(SRC, "grokbot-cypher")]
cenv = dict(env, CYPHER_NO_SYSTEMCTL="1")
run = lambda *a: subprocess.run(cli + list(a), env=cenv, capture_output=True, text=True, timeout=10)
r = run("status"); check("cli status runs", r.returncode == 0 and "drives:" in r.stdout, r.stdout + r.stderr)
r = run("journal", "-n", "3"); check("cli journal prints decisions", r.returncode == 0 and "why:" in r.stdout, r.stdout)
run("mute"); check("cli mute sets the switch", os.path.exists(os.path.join(T, "cfg", "muted")))
run("unmute"); check("cli unmute clears it", not os.path.exists(os.path.join(T, "cfg", "muted")))
run("stop"); check("cli stop sets KILL", os.path.exists(os.path.join(T, "cfg", "KILL")))
run("start"); check("cli start clears KILL", not os.path.exists(os.path.join(T, "cfg", "KILL")))
run("pause", "5"); check("cli pause writes pause_until", float(open(os.path.join(T, "cfg", "pause_until")).read()) > time.time())
run("resume"); check("cli resume clears it", not os.path.exists(os.path.join(T, "cfg", "pause_until")))
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
