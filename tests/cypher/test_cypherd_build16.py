#!/usr/bin/env python3
"""Build 16: Cypher's apartment (the `apartment` feature, where he is in the room, the dash fields the deck reads) and
his body sooner (`body_first`: the next sleep asks for his body first; the interview path makes a pending proposal;
nothing is ever approved here). No root, network or display."""
import importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, io, contextlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "build_files", "rpi5", "cypher")
NOVA = os.path.join(ROOT, "build_files", "rpi5", "nova")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:400]))
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
PX = {"reply": '{"action":"none","params":{},"reason":"x"}', "seen": [], "queue": []}
class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._j(200, {"ok": True})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); PX["seen"].append(body)
        r = PX["queue"].pop(0) if PX["queue"] else PX["reply"]
        self._j(200, {"model": "fake", "choices": [{"message": {"content": r}}], "usage": {}})
port = free_port()
srv = ThreadingHTTPServer(("127.0.0.1", port), Proxy); threading.Thread(target=srv.serve_forever, daemon=True).start()
T = tempfile.mkdtemp()
for n, v in (("token", "k" * 12 + "TokSecret0123456789"), ("topic", "cypher-" + "T0p1cSecretXyz_abcdefgh")):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
SHIPPED = os.path.join(SRC, "cypher-limits.json")
L0 = json.load(open(SHIPPED))
L0["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % port]; L0["brain"]["primary_url"] = L0["brain"]["primary_urls"][0]
L0["brain"]["local"]["enabled"] = False; L0["brain"]["hosted_backup"]["enabled"] = False
L0["failover"]["enabled"] = False; L0["camera"]["enabled"] = False; L0["grid"]["enabled"] = False
LIM = os.path.join(T, "limits.json"); json.dump(L0, open(LIM, "w")); os.chmod(LIM, 0o644)
os.environ.update(CYPHER_LIMITS=LIM, CYPHER_LIMITS_DEFAULT=os.path.join(T, "no-image-copy.json"), CYPHER_LIMITS_INSECURE_OK="1",
                  CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"), CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"),
                  CYPHER_NTFY_TOPIC_FILE=os.path.join(T, "topic"), CYPHER_CONFIG_DIR=os.path.join(T, "cfg"),
                  CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_DATA_DIR=os.path.join(T, "data"),
                  CYPHER_PERSONA=os.path.join(SRC, "persona.md"), CYPHER_DRY_RUN="1", TZ="America/New_York",
                  XDG_RUNTIME_DIR=os.path.join(T, "run"), NOVA_DRY_RUN="1",
                  NOVA_KEY_FILE=os.path.join(T, "nova_key"), NOVA_SYS_KEY_FILE=os.path.join(T, "nova_sys_key"),
                  NOVA_AVATAR_CFG=os.path.join(T, "cfg", "avatar.json"), NOVA_VOICE_CFG=os.path.join(T, "cfg", "voice.json"),
                  NOVA_WEB_USERJS=os.path.join(NOVA, "nova-web-user.js"), NOVA_CONFIRM_SOCK=os.path.join(T, "run", "nova", "confirm.sock"))
for d in ("run", "state", "cfg"): os.makedirs(os.path.join(T, d), exist_ok=True)
time.tzset()
def load(path, name, **env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sys.path.insert(0, NOVA)
C = load(os.path.join(SRC, "cypherd.py"), "cypherd_b15", CYPHER_HOST="deck")
sys.path.insert(0, NOVA)
C = load(os.path.join(SRC, "cypherd.py"), "cypherd_b16", CYPHER_HOST="deck")
os.environ["CYPHER_HOST"] = "deck"
L = C.current_limits(C.new_state())
def at(h, m=0, day=16): return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))
now = at(14)
import apartment as APT

# ================= 1. flags =================
check("apartment and body_first are features, on by default", "apartment" in C.FEATURES and "body_first" in C.FEATURES
      and C.feature(L, "apartment") and C.feature(L, "body_first"))
check("the shipped limits carry both", L0["features"].get("apartment") is True and L0["features"].get("body_first") is True)
check("pino_post still locked off", not C.feature(L, "pino_post") and "pino_post" in C.LOCKED_FEATURES)

# ================= 2. where he is in the room =================
st = C.new_state()
def spot(action=None, place="apartment", active=True, t=now, energy=0.6):
    st["place"] = place; st["dash_last"] = {"action": action} if action else {}; st["drives"]["energy"] = energy
    return C.apartment_spot(L, st, active, t)
check("research and codex -> the desk terminal", spot("research_lore") == "desk" and spot("write_codex") == "desk" and spot("look_up") == "desk")
check("thinking / idle -> the window", spot("journal_thought") == "window" and spot("none") == "window" and spot() == "window")
check("resting -> bed", spot("rest") == "bed")
check("drained -> bed", spot("journal_thought", energy=0.05) == "bed")
check("quiet hours with nothing to do -> bed", spot("none", t=at(1)) == "bed")
check("eating -> the sink", spot("eat") == "sink")
check("out in Night City -> out (through the door)", spot("go_to", place="noodle_stall") == "out" and spot(None, place="library") == "out")
check("Alpha holds the mind -> out", spot("none", active=False) == "out")
st["place"] = "apartment"; st["dash_last"] = {"action": "write_codex"}; st["drives"]["energy"] = 0.6
d = C.dash_snapshot(L, st, True, now)
check("dash.json carries spot and the apartment flag", d.get("spot") == "desk" and d.get("apartment") is True, {k: d.get(k) for k in ("spot", "apartment")})
for a_ in ("research_lore", "rest", "eat", "journal_thought", "none"):
    st["dash_last"] = {"action": a_}; d = C.dash_snapshot(L, st, True, now)
    fake = dict(d); fake.pop("spot")
    check("deck fallback mapping agrees for %s" % a_, APT.spot_from_dash(fake) in (d["spot"], "window") and APT.spot_from_dash(d) == d["spot"],
          (APT.spot_from_dash(fake), d["spot"], d["activity"]))
C.set_feature("apartment", False); check("features.json turns the apartment off (dash says so)", C.dash_snapshot(L, st, True, now)["apartment"] is False)
C.set_feature("apartment", None)

# ================= 3. body first =================
check("no body yet -> body_first on", C.body_description() is None and C.body_first_on(L))
check("the world line tells him tonight's first proposal is his body", "FIRST proposal is your body" in C.body_invite(L))
day = "2026-11-15"
D = os.path.join(T, "data", "journal"); os.makedirs(D, exist_ok=True)
with open(os.path.join(D, day + ".jsonl"), "a") as f:
    for i in range(4):
        f.write(json.dumps({"ts": "%sT1%d:00:00-0500" % (day, i), "tick": i, "mood": "content", "brain": "alpha",
                            "choice": {"action": "go_to", "params": {"place": "noodle_stall"}}, "reason": "r"}) + "\n")
BODY = "Lean frame in a charcoal jacket, collar up; a cyan visor line where eyes would be; pink neon piping down one sleeve."
PX["seen"].clear()
PX["reply"] = json.dumps({"memories": ["noodles again"], "add_notes": [], "drop_notes": [],
                          "tune": {"drift": {"boredom": 0.01}, "bias": {"check_grid": 0.1}, "effect_scale": {"boredom": 0.1},
                                   "body": {"description": BODY}, "reason": "a body, finally"}, "reason": "ok"})
st = C.new_state()
s1 = C.maybe_sleep(L, st, at(4, 5, 16))
sent = json.dumps(PX["seen"][-1]) if PX["seen"] else ""
check("the sleep prompt puts the body first", "FIRST, before anything else tonight" in sent)
check("the sleep gets room for a full body (600 tokens)", '"max_tokens": 600' in sent or (PX["seen"] and PX["seen"][-1].get("max_tokens") == 600),
      PX["seen"] and PX["seen"][-1].get("max_tokens"))
props = C.load_proposals()
bp = [c for c in props[-1]["changes"] if c["path"] == "body.description"] if props else []
check("a pending body proposal, kept even with 3 other changes", bp and bp[0]["after"] == BODY and props[-1]["status"] == "pending"
      and props[-1]["changes"][0]["path"] == "body.description", props[-1] if props else None)
check("journal says body_first proposed", s1 and s1.get("body_first") == "proposed", s1 and s1.get("body_first"))
check("nothing applied: still no body until Zack approves", C.body_description() is None)
check("body_first rests while his design waits on Zack", not C.body_first_on(L) and "waiting for Zack" in C.body_invite(L))
check("the interview path refuses while one waits", C.cli_body(["propose"]) == 1)

# a sleep with no body in the reply keeps asking
C.save_proposals([])
PX["reply"] = json.dumps({"memories": ["quiet"], "tune": {"drift": {"boredom": 0.01}, "reason": "x"}, "reason": "ok"})
st = C.new_state(); s2 = C.maybe_sleep(L, st, at(4, 5, 17)) if False else None
st["last_sleep"] = None
with open(os.path.join(D, "2026-11-16.jsonl"), "a") as f:
    f.write(json.dumps({"ts": "2026-11-16T12:00:00-0500", "tick": 9, "mood": "content", "brain": "alpha", "choice": {"action": "none"}, "reason": "r"}) + "\n")
s2 = C.maybe_sleep(L, st, at(4, 5, 17))
check("no body in the reply -> asked again next sleep", s2 and "asked again" in str(s2.get("body_first")), s2 and s2.get("body_first"))
check("still on for next night", C.body_first_on(L))

# the tuning caps would skip it (a proposal already today): the body still goes, alone
C.save_proposals([{"id": 7, "ts": "x", "epoch": at(3, 0, 18), "day": "2026-11-17", "brain": "alpha", "changes": [{"path": "drift.boredom", "before": 0, "after": 0.01}], "status": "denied"}])
with open(os.path.join(D, "2026-11-17.jsonl"), "a") as f:
    f.write(json.dumps({"ts": "2026-11-17T12:00:00-0500", "tick": 10, "mood": "content", "brain": "alpha", "choice": {"action": "none"}, "reason": "r"}) + "\n")
PX["reply"] = json.dumps({"memories": ["x"], "tune": {"drift": {"boredom": 0.01}, "body": {"description": BODY}, "reason": "mine"}, "reason": "ok"})
st = C.new_state(); s3 = C.maybe_sleep(L, st, at(4, 5, 18))
props = C.load_proposals()
check("daily cap hit -> a body-only proposal still goes to Zack", s3 and s3.get("body_first") == "proposed" and props[-1].get("changes")[0]["path"] == "body.description"
      and len(props[-1]["changes"]) == 1, (s3 and s3.get("tuning"), s3 and s3.get("body")))

# interview path
C.save_proposals([])
PX["reply"] = json.dumps({"answer": "I want to look like I belong to the alley.", "body": BODY})
with contextlib.redirect_stdout(io.StringIO()) as out:
    rc = C.cli_body(["propose"])
props = C.load_proposals()
check("body propose: his answer becomes a pending proposal (interview source)", rc == 0 and props and props[-1].get("source") == "interview"
      and props[-1]["status"] == "pending" and props[-1]["changes"][0]["after"] == BODY, (rc, out.getvalue()[-300:]))
check("the interview is saved", "body" in (json.loads(open(C.INTERVIEWS_FILE).read().strip().split("\n")[-1]) or {}))
check("still nothing applied", C.body_description() is None)
C.save_proposals([])
PX["reply"] = json.dumps({"answer": "password: hunter2", "body": "my password is hunter2 and the camera.front token"})
with contextlib.redirect_stdout(io.StringIO()):
    rc = C.cli_body(["propose"])
check("a body with forbidden words is refused", rc == 1 and not C.load_proposals())
# approving is Zack's: tuning approve applies it (sanity, through the existing path)
C.save_proposals([])
with contextlib.redirect_stdout(io.StringIO()):
    PX["reply"] = json.dumps({"answer": "ok", "body": BODY}); C.cli_body(["propose"])
nid = C.load_proposals()[-1]["id"]
with contextlib.redirect_stdout(io.StringIO()):
    C.cli(["tuning", "approve", str(nid)])
check("after Zack's approve the body is his", C.body_description() == BODY)
check("body_first is done once he has a body", not C.body_first_on(L))
C.write_body(None)

# ================= 4. wiring =================
cli = open(os.path.join(SRC, "grokbot-cypher")).read()
check("grokbot-cypher has body", '"body"' in cli and "body propose" in cli)
nn = open(os.path.join(NOVA, "nova_native.py")).read()
check("the face shows the apartment by default and follows the flag", "apartment_wanted" in nn and 'default=os.environ.get("NOVA_VIEW", "auto")' in nn
      and "AptGLView" in nn)
inst = open(os.path.join(ROOT, "build_files", "rpi5-nova.sh")).read()
check("the image installs the apartment", "apartment.py apartment_gl.py apartment_body_placeholder.json" in inst)

srv.shutdown()
print("%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
