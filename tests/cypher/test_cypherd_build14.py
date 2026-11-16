#!/usr/bin/env python3
"""Build 14: a wrapping chat bar inside the centre column, lessons from mistakes (Zack's corrections and
validator catches, deduped, in every prompt, flagged to Nova when repeated), threads that only count real
opens (5 open, 4 a day, configurable), a 10-minute journal gap, "none" as a last resort while Cypher has
energy, higher ceilings for the free actions, image defaults filling what an edited /etc limits file
lacks, and a chat-triggered power_off that only a Confirm click on the deck's screen can run.
No root, network or real display (the GTK layout probe uses a private broadwayd when it exists)."""
import importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
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
C = load(os.path.join(SRC, "cypherd.py"), "cypherd_b14", CYPHER_HOST="deck")
A = load(os.path.join(SRC, "cypherd.py"), "cypherd_b14a", CYPHER_HOST="alpha")
os.environ["CYPHER_HOST"] = "deck"
L = C.current_limits(C.new_state())
def at(h, m=0, day=16): return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))
now = at(14)
P = {"local_time": "Monday 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": [], "brain": "alpha"}
Q = dict(P, quiet_hours=True, local_time="Monday 1:00 AM", presence="away")
J = json.dumps
perceive = lambda p: (lambda L, n: dict(p))
def run_tick(st, p=P, n=now, inbox=None, talk=None):
    return C.tick(L, st, n, perceive_fn=perceive(p), camera_fn=lambda L, s, x: [],
                  inbox_fn=inbox or (lambda L, s, x: []), talk_fn=talk or (lambda *a: 0))
def journal_text():
    d = os.path.join(T, "data", "journal")
    return "".join(open(os.path.join(d, f)).read() for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""
def lessons(): return {r["key"]: r for r in C.load_lessons()}
def fresh_lessons():
    C.save_lessons([])
    try: os.remove(C.NOVA_FLAGS_FILE)
    except FileNotFoundError: pass

# ================= 6. limits: ceilings and shipped defaults =================
B = C.LIMIT_BOUNDS
check("free ceilings raised: visit_pino 12/h 100/day, go_to 30/300, glance and notes 12/100",
      B["visit_pino"] == {"per_hour": (0, 12), "per_day": (0, 100)} and B["go_to"] == {"per_hour": (0, 30), "per_day": (0, 300)}
      and B["glance_screen"] == {"per_hour": (0, 12), "per_day": (0, 100)} and B["show_note"] == {"per_hour": (0, 12), "per_day": (0, 100)})
check("paid and outward ceilings unchanged (look_up is free now: item 10)", B["web_search"] == B["x_lookup"] == {"per_hour": (0, 6), "per_day": (0, 30)}
      and B["message_zack"] == {"per_hour": (0, 10), "per_day": (0, 50)} and B["speak"] == {"per_hour": (0, 10), "per_day": (0, 60)}
      and B["ask_nova"] == {"per_day": (0, 3)} and B["request_account"] == {"per_day": (0, 1), "per_week": (0, 2)}
      and B["propose_code"] == {"per_day": (0, 2), "per_week": (0, 5)})
check("journal_thought: same caps, min_gap_s now settable", B["journal_thought"]["per_hour"] == (0, 60) and "min_gap_s" in B["journal_thought"])
S = C.load_limits(SHIPPED)["actions"]
DECK_LIVE = {"visit_pino": (4, 24), "go_to": (12, 100), "glance_screen": (6, 30), "show_note": (6, 30),
             "web_search": (4, 20), "x_lookup": (4, 20), "look_up": (4, 20)}       # read from the deck's /etc file, Nov 15 7:10 PM
check("shipped defaults match what is live on the deck", all((S[a]["per_hour"], S[a]["per_day"]) == v for a, v in DECK_LIVE.items())
      and S["journal_thought"]["per_hour"] == 4 and S["message_zack"]["per_hour"] == 3 and S["message_zack"]["per_day"] is None,
      {a: (S[a].get("per_hour"), S[a].get("per_day")) for a in DECK_LIVE})
check("journal gap 10 min in the shipped file", S["journal_thought"]["min_gap_s"] == 600)
setter = os.path.join(SRC, "grokbot-set-cypher-limit")
def set_limit(*args, dest=None, extra=None):
    dest = dest or os.path.join(T, "set-limits.json")
    if not os.path.exists(dest): shutil.copy(SHIPPED, dest)
    env = dict(os.environ, GROKBOT_CYPHER_LIMITS_FILE=dest, GROKBOT_CYPHER_LIMITS_NOROOT="1", CYPHER_LIB=SRC, **(extra or {}))
    return subprocess.run([sys.executable, setter, *args], capture_output=True, text=True, env=env)
r = set_limit("visit_pino", "per_hour", "12")
check("limits set visit_pino per_hour 12 works", r.returncode == 0, r.stderr)
check("visit_pino per_hour 13 refused", set_limit("visit_pino", "per_hour", "13").returncode != 0)
check("go_to per_day 300 works", set_limit("go_to", "per_day", "300").returncode == 0)
check("web_search per_hour 7 still refused (paid)", set_limit("web_search", "per_hour", "7").returncode != 0)
r = set_limit("journal_thought", "min_gap_s", "600")
check("limits set journal_thought min_gap_s 600 works", r.returncode == 0 and json.load(open(os.path.join(T, "set-limits.json")))["actions"]["journal_thought"]["min_gap_s"] == 600, r.stderr)
check("min_gap_s cannot be none", set_limit("journal_thought", "min_gap_s", "none").returncode != 0)

# ================= image defaults fill an edited /etc file =================
img = os.path.join(T, "image-limits.json"); shutil.copy(SHIPPED, img); os.chmod(img, 0o644)
old = json.load(open(SHIPPED)); old.pop("threads"); old["actions"].pop("review_lessons")
old["actions"]["journal_thought"]["min_gap_s"] = 900; old.pop("active_heartbeat_s")
etc = os.path.join(T, "etc-limits.json"); json.dump(old, open(etc, "w")); os.chmod(etc, 0o644)
C.LIMITS_DEFAULT = img
M = C.load_limits(etc)
check("edited /etc file: new action and blocks come from the image copy", "review_lessons" in M["actions"] and M["threads"]["max_open"] == 5
      and M["active_heartbeat_s"] == 180)
check("edited /etc file: its own values win (journal gap 900, message_zack per_day null)",
      M["actions"]["journal_thought"]["min_gap_s"] == 900 and M["actions"]["message_zack"]["per_day"] is None)
C.LIMITS_DEFAULT = os.path.join(T, "no-image-copy.json")
check("no image copy -> the file alone", "review_lessons" not in C.load_limits(etc)["actions"])
r = set_limit("review_lessons", "per_hour", "6", dest=etc, extra={"CYPHER_LIMITS_DEFAULT": img})
check("limits set works for an action only the image copy has", r.returncode == 0 and json.load(open(etc))["actions"]["review_lessons"]["per_hour"] == 6, r.stderr)

# ================= 3. threads =================
st = C.new_state()
for g in ("find out what Pino's town is built with", "learn the noodle stall owner's name", "map the street below my place", "read up on the tank motors"):
    C.apply_thread(st, {"open": g}, now, L)
check("4 opened a day", len(st["threads"]) == 4 and C.apply_thread(st, {"open": "a fifth real goal today"}, now, L) == "thread refused: 4 opened today")
check("opens are recorded with their thread id", all(isinstance(o, list) and len(o) == 2 for o in st["threads_opened"]))
st = C.new_state()
C.apply_thread(st, {"open": "drifts"}, now, L); C.apply_thread(st, {"open": "#2 x"}, now, L)
check("refused junk never counts", st["threads_opened"] == [] and C.thread_opens(st, now) == [])
st = C.new_state()      # build 12 state: junk opened, bare epochs in threads_opened
st["threads"] = [{"id": 1, "text": "drifts", "since": now - 600, "touched": now - 600}, {"id": 2, "text": "#1 drifts", "since": now - 500, "touched": now - 500}]
st["threads_opened"] = [now - 600, now - 500]; st["thread_seq"] = 2
C.threads_live(st, now, L)
check("build 13's junk cleanup gives the opens back", C.thread_opens(st, now) == [] and st["threads"] == [], st)
st["threads"] = [{"id": 3, "text": "watch Pino's feed later", "since": now - 400, "touched": now - 400}]
st["threads_opened"] = [now - 400, now - 300]
check("a legacy epoch still counts when its thread is live", C.thread_opens(st, now) == [[now - 400, 3]])
st = C.new_state()
C.apply_thread(st, {"open": "a real goal number one"}, now, L)
st["threads"][0]["text"] = "x"          # became junk (e.g. an old build wrote it)
C.threads_live(st, now, L)
check("a thread thrown out later as junk also gives its open back", C.thread_opens(st, now) == [])
st = C.new_state()
for i in range(5): st["threads"].append({"id": i + 1, "text": "real goal number %d" % i, "since": now - 90000, "touched": now})
check("5 open at most", C.apply_thread(st, {"open": "a sixth real goal"}, now, L) == "thread refused: already 5 open")
L3 = dict(L, threads={"max_open": 3, "opens_per_day": 1})
check("caps come from the limits file", C.apply_thread(st, {"open": "another real goal"}, now, L3) == "thread refused: already 3 open")
st = C.new_state(); C.apply_thread(st, {"open": "one real goal today"}, now, L3)
check("opens_per_day from the limits file", C.apply_thread(st, {"open": "two real goals today"}, now, L3) == "thread refused: 1 opened today")
for bad in ({"max_open": 0}, {"opens_per_day": 13}, {"max_open": "5"}, []):
    try:
        C.validate_limits(dict(json.loads(json.dumps(L0)), threads=bad)); res = False
    except C.ConfigError:
        res = True
    check("bad threads block refused: %r" % (bad,), res)

# ================= 4. journal pacing =================
st = C.new_state(); st["recent"] = [[now - 300, "journal_thought"]]
check("journal refused 5 min after the last", "journal thought" in (C.blocked(L, st, P, "journal_thought", now) or ""))
check("journal fine after 10 min", C.blocked(L, st, P, "journal_thought", now + 301) is None)
check("still 'only when something new happened'", "only when something new happened" in C.MANIFEST_TEXT["journal_thought"])

# ================= 2. lessons =================
fresh_lessons(); C.save_state(os.path.join(T, "state", "drives.json"), C.new_state())
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "journal_thought", "params": {}, "reason": "x"})] * 2
run_tick(st)
check("validator catch -> a lesson (needs text)", "needs_text" in lessons() and lessons()["needs_text"]["source"] == "validator", lessons())
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "journal_thought", "params": {"text": "It is the dead of night here."}, "reason": "x"})] * 2
run_tick(st)
check("false quiet-hours/night claim -> the time lesson", "time_claim" in lessons())
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "go_to", "params": {"place": "apartment"}, "reason": "x"})]
run_tick(st)
check("claimed a place he is already at -> lesson", "go_to_here" in lessons())
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "rest", "params": {}, "reason": "x", "thread": {"open": "drifts"}})]
L["features"] = {"loops": False}
run_tick(st)
L.pop("features", None)
check("junk thread -> lesson", "thread_words" in lessons())
for i in range(2): C.add_lesson("needs_text", "Put the words in params.text for journal thoughts, notes, messages and speech.", "validator", now + i)
lt = lessons()
check("deduped with a count and timestamps", lt["needs_text"]["count"] == 3 and lt["needs_text"]["first"] < lt["needs_text"]["last"], lt["needs_text"])
fl = json.load(open(C.NOVA_FLAGS_FILE))
check("repeated 3 times -> flagged to Nova in its own file", lt["needs_text"].get("flagged") and fl[-1]["key"] == "needs_text" and fl[-1]["count"] == 3, fl)
check("the flag is journaled", "lesson_flagged" in journal_text())
check("flagging never spends ask_nova (no asks file)", not os.path.exists(C.nova_outbox()) or C.load_asks() == [])
C.add_lesson("needs_text", "Put the words in params.text.", "validator", now + 5)
check("flagged once, not on every repeat", len(json.load(open(C.NOVA_FLAGS_FILE))) == 1)
# Zack's corrections
spool = os.path.join(T, "state", "talk-spool.jsonl")
def talk(user, reply="ok"):
    with open(spool, "a") as f: f.write(J({"ts": now, "kind": "turn", "via": "typed", "user": user, "reply": reply}) + "\n")
    C.talk_step(L, C.new_state(), now, P)
talk("No, that's wrong, it's not quiet hours, it's 5 PM")
z = [r for r in C.load_lessons() if r["source"] == "zack"]
check("Zack correcting him in chat -> a lesson in his words", z and "it's not quiet hours" in z[-1]["text"] and z[-1]["text"].startswith("Zack corrected you:"), z)
talk("sounds good, go walk around Night City")
check("a plain message is not a correction", len([r for r in C.load_lessons() if r["source"] == "zack"]) == 1)
talk("No, that's wrong, it's not quiet hours, it's 5 PM")
check("the same correction twice is one lesson, count 2", [r["count"] for r in C.load_lessons() if r["source"] == "zack"] == [2])
talk("what did you find?", "I read about it. (Nothing started yet. Ask me again and I'll run it.)")
check("a claim with nothing behind it in chat -> lesson", "claimed_action" in lessons())
st = C.new_state(); st["drives"]["energy"] = 0.3
run_tick(st, n=now + 100, inbox=lambda L, s, x: [[now + 50, "you didn't actually visit Pino, stop claiming that"]])
check("a correction from his phone -> lesson too", any("didn't actually visit Pino" in r["text"] for r in C.load_lessons()))
C.lesson_from_zack("wrong, the token: abc123def456ghi789jkl012", now)
check("lesson text is scrubbed (no links or secrets)", C.lesson_from_zack("you're wrong, see https://evil.example/x", now) is None
      and "abc123def456" not in json.dumps(C.load_lessons()))
top = C.ranked_lessons(now + 200)
check("ranking: Zack's corrections first, then repeats", top[0]["source"] == "zack" and len(top) == C.LESSON_PROMPT_N, [r["key"] for r in top])
st = C.new_state()
m = C.build_messages(L, st, P, now + 200)
u = m[1]["content"]
check("top lessons in the tick prompt", "lessons (from your own mistakes)" in u and top[0]["text"][:30] in u, u[:600])
check("prompt still under the 5200-char trim", len(m[0]["content"]) + len(m[1]["content"]) + 2 <= 5200, len(m[0]["content"]) + len(m[1]["content"]))
C.write_dash(L, st, True, now + 200)
dash = json.load(open(os.path.join(T, "state", "dash.json")))
check("dash: lesson count and top lessons", dash["lesson_count"] == len(C.load_lessons()) and len(dash["lessons"]) == 3)
CL = load(os.path.join(NOVA, "cypher_link.py"), "cypher_link_b14")
check("lessons in the chat prompt too", "lessons from your own mistakes" in CL.state_lines(now + 200), CL.state_lines(now + 200)[:300])
check("review_lessons offered while he has lessons", "review_lessons" in m[0]["content"])
v = C.validate(L, st, P, {"action": "review_lessons", "params": {}}, now + 200)
res = C.execute(v[0], v[1], L, st, P)
check("review_lessons: one lesson comes back as found", v[2] == "ok" and res == "ok" and st["found"][-1][1] == "lesson", (v, res, st.get("found")))
check("review_lessons narrated", C.narrate("review_lessons", {}, "ok", "ok") == "Went over one of my lessons.")
check("sleep sees repeated lessons as fix material", "repeated lessons" in C.lessons_sleep_context() and "x" in C.lessons_sleep_context())
fresh_lessons()
check("no lessons -> review_lessons left out", C.blocked(L, C.new_state(), P, "review_lessons", now) == "no lessons yet")
r = subprocess.run([sys.executable, os.path.join(SRC, "cypherd.py"), "lessons"], capture_output=True, text=True, env=dict(os.environ))
check("grokbot-cypher lessons (cypherd lessons) works", r.returncode == 0 and "no lessons yet" in r.stdout, r.stdout + r.stderr)
try:
    import cairo  # noqa
    PN = load(os.path.join(SRC, "cypher_panels.py"), "panels_b14")
    out = os.path.join(T, "p.png"); PN.render_png(out, dict(dash, epoch=now), size=(1280, 720), now=now, avatar=False)
    check("panel renders with the lesson count", os.path.getsize(out) > 1000)
    check("text column sits between the panels at 1280x720", PN.text_column(1280, 720)[0] >= PN.MARGIN + PN.COL_W
          and sum(PN.text_column(1280, 720)) <= 1280 - PN.MARGIN - PN.COL_W, PN.text_column(1280, 720))
    check("text column, panels hidden: up to 720 px centred", PN.text_column(1280, 720, False) == (280, 720))
    check("text column scales with the screen", all(PN.text_column(w, h)[0] >= (PN.MARGIN + PN.COL_W) * h / 720.0
                                                    for w, h in ((1280, 720), (1920, 1080), (1024, 600), (1366, 768))))
except ImportError:
    check("cairo missing: panel checks skipped", True)

# ================= 5. less idle =================
fresh_lessons()
st = C.new_state(); st["drives"]["energy"] = 0.7
PX["queue"] = [J({"action": "none", "params": {}, "reason": "content"}), J({"action": "visit_pino", "params": {}, "reason": "see Pino"})]
seen0 = len(PX["seen"]); e = run_tick(st, n=now + 1000)
check("none while able -> one more try that names the free options", e["choice"]["action"] == "visit_pino" and "second try" in e.get("note", "")
      and "Doing nothing is a last resort" in PX["seen"][-1]["messages"][-1]["content"], e)
check("that try costs one extra call", len(PX["seen"]) - seen0 == 2)
check("picking none while able is a lesson", "none_while_able" in lessons())
st = C.new_state(); st["drives"]["energy"] = 0.7
PX["queue"] = [J({"action": "none", "params": {}, "reason": "x"}), J({"action": "none", "params": {}, "reason": "x"})]
e = run_tick(st, n=now + 2000)
check("still none -> a concrete free activity of our own", e["choice"]["action"] in ("visit_pino", "review_lessons", "go_to") and "chose" in e.get("note", ""), e)
check("never a paid action", all(a not in C.FREE_ACTIVITIES for a in ("web_search", "x_lookup", "message_zack", "speak", "request_account")))
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "none", "params": {}, "reason": "x"})]
check("low energy: none stays none", run_tick(st, n=now + 3000)["choice"]["action"] == "none")
st = C.new_state(); st["drives"]["energy"] = 0.8
PX["queue"] = [J({"action": "none", "params": {}, "reason": "x"})]
check("quiet hours (his sleep): none stays none", run_tick(st, p=Q, n=at(1)) ["choice"]["action"] == "none")
st = C.new_state(); st["drives"]["energy"] = 0.7
st["recent"] = [[now - 10, a] for a in ("visit_pino",) * 4] + [[now - 10, "go_to"]] * 12
check("everything free capped -> none allowed", C.steer_from_none(L, st, dict(P, presence="locked"), [], "", {"action": "none"}, now)[0] in ("none", "review_lessons", "look_up", "journal_thought"))
check("rest still offered when drained", "rest" in C.QUIET_ACTIONS and C.DRAINED_HINT.startswith("You are drained"))
st = C.new_state(); st["drives"]["energy"] = 0.7
check("heartbeat: 3 min while able, 10 min otherwise", C.heartbeat(L, st, P) == 180 and C.heartbeat(L, st, Q) == 600)
st["drives"]["energy"] = 0.3
check("heartbeat: 10 min with low energy", C.heartbeat(L, st, P) == 600)

# ================= 8. power_off =================
N = load(os.path.join(NOVA, "novad.py"), "novad_b14")
check("power_off is a chat tool", any(t["function"]["name"] == "power_off" for t in N.tool_schema()))
seen = []; script = []
N.chat = lambda messages, key: (seen.append(messages), script.pop(0))[1]; N.read_key = lambda: "test-key"
script[:] = [{"content": "", "tool_calls": [{"id": "1", "function": {"name": "power_off", "arguments": "{}"}}]}]
ev = []; N.handle_prompt("power down", ev.append)
cf = [x["confirm"] for x in ev if "confirm" in x]
check("chat intent -> an on-screen dialog: 'Shut Cypher down now?', Confirm/Cancel, 30 s",
      cf and cf[0]["text"] == "Shut Cypher down now?" and cf[0]["physical"] is True and cf[0]["ttl"] == 30
      and cf[0]["yes_label"] == "Confirm" and cf[0]["no_label"] == "Cancel", ev)
pid = cf[0]["id"]
REQ = os.path.join(T, "state", "shutdown-request.json")
res = N.confirm(pid, True)
check("a yes over HTTP (an agent, a script, the phone) is refused", res.get("error") == "needs_click" and not os.path.exists(REQ), res)
check("the dialog stays up after a refused yes", pid in N.PENDING)
res = N.confirm(pid, False)
check("Cancel does nothing", res.get("reply") == "Okay, I won't." and not os.path.exists(REQ) and pid not in N.PENDING, res)
p2 = N.power_off_pending(); N.PENDING[p2["confirm_id"]]["exp"] = time.time() - 1
res = N.confirm(p2["confirm_id"], True, physical=True)
check("timeout (expired) does nothing, even with a click", res.get("error") == "expired" and not os.path.exists(REQ), res)
script[:] = [{"content": "", "tool_calls": [{"id": "1", "function": {"name": "power", "arguments": J({"action": "shutdown"})}}]}]
ev = []; N.handle_prompt("shut down", ev.append)
check("the old power/shutdown tool goes through the same dialog", [x["confirm"]["physical"] for x in ev if "confirm" in x] == [True])
# --- build 15: the 10:16 PM bug: the model said "Shutting down. Confirm on the screen" with no tool call ---
N.PENDING.clear(); seen.clear()
script[:] = [{"content": "Shutting down. Confirm on the screen if you mean it."}]   # what the model really did
ev = []; N.handle_prompt("Shut down", ev.append)
cf = [x["confirm"] for x in ev if "confirm" in x]
check("b15: 'Shut down' raises the physical dialog without asking the model", cf and cf[0]["physical"] is True
      and cf[0]["text"] == "Shut Cypher down now?" and not seen and len(script) == 1 and cf[0]["id"] in N.PENDING, (ev, seen))
check("b15: ...and nothing runs until the click", not os.path.exists(REQ) and N.confirm(cf[0]["id"], True).get("error") == "needs_click")
for ptxt in ("shut down", "Shutdown.", "power off", "please power down now", "Cypher, shut yourself down", "turn yourself off", "ok shut down please"):
    N.PENDING.clear(); script[:] = []; ev = []; N.handle_prompt(ptxt, ev.append)
    check("b15: intent %r -> dialog" % ptxt, [x["confirm"]["physical"] for x in ev if "confirm" in x] == [True], ev)
for ptxt in ("shut down the terminal", "how do I shut down Alpha?", "don't shut down", "what happens when you power off?",
             "close the browser", "shut up"):
    check("b15: not a shutdown request: %r" % ptxt, not N.power_intent(ptxt))
N.PENDING.clear()
# a false claim with no dialog: one nudge, then the reply is replaced
script[:] = [{"content": "Shutting down. Confirm on the screen if you mean it."},
             {"content": "Okay. Tap Confirm on the screen when you're ready."}]
ev = []; N.handle_prompt("can you turn the deck off for me in a bit", ev.append)
rep = [x["reply"] for x in ev if "reply" in x]
check("b15: a reply claiming a dialog that was never raised is nudged, then replaced",
      rep == [N.NO_DIALOG_TEXT] and not [x for x in ev if "confirm" in x] and not N.PENDING
      and any(m.get("content") == N.CONFIRM_NUDGE for m in seen[-1]), (ev, seen[-1][-2:]))
script[:] = [{"content": "Shutting down. Confirm on the screen if you mean it."},
             {"content": "", "tool_calls": [{"id": "2", "function": {"name": "power_off", "arguments": "{}"}}]}]
ev = []; N.handle_prompt("can you turn the deck off for me in a bit", ev.append)
check("b15: after the nudge the model can still call power_off -> the real dialog",
      [x["confirm"]["physical"] for x in ev if "confirm" in x] == [True] and not [x for x in ev if "reply" in x], ev)
N.PENDING.clear()
script[:] = [{"content": "Locking the screen now. Hit Yes on the dialog."}, {"content": "I can lock the screen if you want; say so."}]
ev = []; N.handle_prompt("lock it maybe?", ev.append)
check("b15: an honest retry after the nudge is kept", [x.get("reply") for x in ev if "reply" in x] == ["I can lock the screen if you want; say so."], ev)
for ok_txt in ("I can confirm it's 2026.", "Terminal's up. Super+Enter if you need another.", "The noodle stall was quiet tonight.",
               "Say shut down and I'll put a dialog up."):
    check("b15: no false alarm on %r" % ok_txt, not N.confirm_claim(ok_txt))
for bad in ("Shutting down. Confirm on the screen if you mean it.", "Tap Confirm on the screen.", "Powering off now.",
            "The dialog is up, hit Confirm.", "Press the Yes button to restart.", "Restarting now."):
    check("b15: claim caught: %r" % bad, N.confirm_claim(bad))
script[:] = [{"content": "", "tool_calls": [{"id": "3", "function": {"name": "power", "arguments": J({"action": "lock"})}}]}]
ev = []; N.handle_prompt("lock the screen", ev.append)
check("b15: a real pending (lock) still reaches the dialog", len([x for x in ev if "confirm" in x]) == 1 and not [x for x in ev if "reply" in x], ev)
N.PENDING.clear(); kinds = []; _rt = N.cypher_link.record_turn
N.cypher_link.record_turn = lambda prompt, reply, via="typed", tools=(), kind="turn", now=None: kinds.append((kind, reply, [t["tool"] for t in tools]))
script[:] = []; ev = []; N.handle_prompt("Shut down", ev.append)
N.cypher_link.record_turn = _rt; N.PENDING.clear()
check("b15: the journal logs 'Shut down' as asks_confirm with power_off pending", kinds == [("asks_confirm", "Shut Cypher down now?", ["power_off"])], kinds)
check("b15: TOOL_RULES forbid claiming a dialog", "unless a tool returned pending this turn" in N.TOOL_RULES)
N.PENDING.clear()
N.serve_confirm_socket()
sk = os.environ["NOVA_CONFIRM_SOCK"]
check("confirm socket is owner-only", oct(os.stat(sk).st_mode & 0o777) == "0o600" and oct(os.stat(os.path.dirname(sk)).st_mode & 0o777) == "0o700")
def sock_send(obj):
    s = socket.socket(socket.AF_UNIX); s.connect(sk); s.sendall((J(obj) + "\n").encode())
    r = json.loads(s.makefile("rb").readline()); s.close(); return r
p3 = N.power_off_pending()
check("a socket message that is not a click is refused", sock_send({"id": p3["confirm_id"], "yes": True}).get("error") == "bad"
      and p3["confirm_id"] in N.PENDING)
logs = []; N.log = lambda *a: logs.append(" ".join(str(x) for x in a))
res = sock_send({"id": p3["confirm_id"], "yes": True, "via": "click"})
check("a real Confirm click runs it: request file, stop cypherd, then poweroff",
      "Shutting down" in str(res.get("reply")) and os.path.exists(REQ)
      and [l for l in logs if l.startswith("DRY-RUN systemctl")] == ["DRY-RUN systemctl --user stop cypherd.service", "DRY-RUN systemctl poweroff"], (res, logs))
NN = sys.modules.get("nova_native")
src = open(os.path.join(NOVA, "nova_native.py")).read()
check("deck app: yes needs a click (Enter, voice, a stray key are refused)", "if self.pend_phys and yes and not click:" in src
      and 'lambda _b, y=yes: self.answer(y, click=True)' in src and "return self.bg(lambda: confirm_click(pid, yes), done)" in src)
check("deck app: the dialog cancels itself at the ttl", 'self.pendT = self.later((c.get("ttl") or 60) * 1000, expire)' in src)
# cypherd side: journal on the way down, Alpha takes over normally, ticks can't reach it
e = C.shutdown_note(time.time())
check("cypherd journals 'shutdown requested by Zack' and clears the request", e and e["why"] == "shutdown requested by Zack"
      and "shutdown requested by Zack" in journal_text() and not os.path.exists(REQ))
msrc = open(os.path.join(SRC, "cypherd.py")).read()
i, j = msrc.find("    shutdown_note(time.time())"), msrc.find("release(L, st, handoff=True)                  # clean stop")
check("the note comes before the clean handoff (deck_stopped -> Alpha takes over)", 0 < i < j)
json.dump({"ts": time.time()}, open(REQ, "w"))
check("the Alpha standby never journals or acts on it", A.shutdown_note(time.time()) is None)
json.dump({"ts": time.time() - 3600}, open(REQ, "w"))
check("a stale request is ignored", C.shutdown_note(time.time()) is None)
check("ticks can't trigger it: no power action in cypherd", "power_off" not in L["actions"] and "power_off" not in C.MANIFEST_TEXT
      and C.validate(L, C.new_state(), P, {"action": "power_off", "params": {}}, now)[2].startswith("rejected: unknown action"))
st = C.new_state(); st["drives"]["energy"] = 0.3
PX["queue"] = [J({"action": "power_off", "params": {}, "reason": "tired"})]
e = run_tick(st, n=now + 5000)
check("a tick choosing power_off is refused", e["choice"]["action"] == "none" and "unknown action" in e["validator"] and not os.path.exists(REQ), e)
check("cypherd never runs poweroff", "systemctl\", \"poweroff" not in msrc and "systemctl poweroff" not in msrc)
check("chat queue can't reach it either", "power_off" not in CL.QUEUEABLE)
rule = open(os.path.join(ROOT, "system_files", "usr", "share", "polkit-1", "rules.d", "50-grokbot-cypher-poweroff.rules")).read()
check("privilege: one polkit rule, power-off only, kiosk user only", rule.count("action.id ==") == 2
      and "org.freedesktop.login1.power-off" in rule and 'subject.user == "grokbot"' in rule
      and not any(w in rule for w in ("reboot", "suspend", "hibernate", "ignore-inhibit", "manage-units")))
check("privilege: no sudo grant for it", not any("poweroff" in open(os.path.join(dp, f), errors="ignore").read()
      for dp, _, fs in os.walk(os.path.join(ROOT, "system_files")) for f in fs if "sudoers" in dp or "sudo" in f))

# ================= 9. readable journal: cypher_journal + `grokbot-cypher journal` =================
CJ = load(os.path.join(SRC, "cypher_journal.py"), "cypher_journal_b14")
jd9 = os.path.join(T, "j9"); os.makedirs(os.path.join(jd9, "journal"))
with open(os.path.join(jd9, "journal", "2026-11-14.jsonl"), "w") as f:
    f.write(J({"ts": "2026-11-14T23:50:00-05:00", "choice": {"action": "rest", "params": {}}, "reason": "late", "validator": "ok", "result": "ok"}) + "\n")
with open(os.path.join(jd9, "journal", "2026-11-15.jsonl"), "w") as f:
    for e in ({"ts": "2026-11-15T19:05:00-05:00", "brain": "alpha", "choice": {"action": "look_up", "params": {"topic": "neon"}},
               "reason": "curious, token=" + "k" * 12 + "TokSecret0123456789", "validator": "ok", "result": "ok", "found": "Neon is a noble gas. " * 12},
              {"ts": "2026-11-15T19:07:00-05:00", "event": "talk", "user": "hi there", "reply": "hey Zack"},
              {"ts": "2026-11-15T19:06:00-05:00", "host": "alpha", "choice": {"action": "go_to", "params": {"place": "noodle_stall"}},
               "model_choice": "go_to", "reason": "hungry", "validator": "rejected: go_to already at noodle_stall"},
              {"ts": "2026-11-15T19:08:00-05:00", "event": "shutdown", "why": "shutdown requested by Zack"}):
        f.write(J(e) + "\n")
    f.write("not json\n")
rows = CJ.entries(limit=10, data_dir=jd9)
check("journal entries: newest first across days, merged Alpha lines sorted", [r["ts"][11:16] for r in rows] == ["19:08", "19:07", "19:06", "19:05", "23:50"], [r["ts"] for r in rows])
check("journal entries: time in ET", rows[0]["time"] == "7:08 PM ET", rows[0])
look = rows[3]
check("journal entries: full what/why/result, no truncation", look["what"] == "look up: neon" and look["result"].startswith("found: Neon is a noble gas.")
      and len(look["result"]) > 200, look)
check("journal entries: secrets scrubbed", "TokSecret" not in json.dumps(rows) and "[redacted]" in look["reason"], look["reason"])
check("journal entries: a refusal says what was tried and why", rows[2]["kind"] == "refused" and rows[2]["what"] == "tried go_to: noodle_stall"
      and "already at" in rows[2]["result"] and rows[2]["host"] == "alpha", rows[2])
check("journal entries: talk shows both sides", rows[1]["what"] == "Zack: hi there" and rows[1]["result"] == "Cypher: hey Zack", rows[1])
check("journal entries: paging by offset", [r["ts"] for r in CJ.entries(limit=2, offset=3, data_dir=jd9)] == [rows[3]["ts"], rows[4]["ts"]])
cli = os.path.join(SRC, "grokbot-cypher")
r = subprocess.run([sys.executable, cli, "journal", "-n", "3"], capture_output=True, text=True, env=dict(os.environ, CYPHER_DATA_DIR=jd9, COLUMNS="80"))
check("CLI journal: readable full entries, newest first", r.returncode == 0 and r.stdout.startswith("2026-11-15 7:08 PM ET  EVENT")
      and "  shutdown\n  why: shutdown requested by Zack" in r.stdout and "{" not in r.stdout, r.stdout + r.stderr)
check("CLI journal: lines wrap to the terminal", max(len(l) for l in r.stdout.splitlines()) <= 80, r.stdout)
r = subprocess.run([sys.executable, cli, "journal", "--raw", "-n", "2"], capture_output=True, text=True, env=dict(os.environ, CYPHER_DATA_DIR=jd9))
check("CLI journal --raw keeps the old view", r.returncode == 0 and "[shutdown]" in r.stdout, r.stdout + r.stderr)
pn = open(os.path.join(SRC, "cypher_panels.py")).read()
CPm = load(os.path.join(SRC, "cypher_panels.py"), "cypher_panels_b14") if importlib.util.find_spec("cairo") else None
if CPm:
    jx, jy, jw, jh = CPm.journal_rect(1280, 720)
    check("panel: JOURNAL tap region is the right column's journal panel", (round(jx), round(jy), round(jw), round(jh)) == (996, 124, 270, 226))
    check("panel: a tap in the centre is not the journal", not CPm.in_journal(1280, 720, 640, 300) and CPm.in_journal(1280, 720, 1100, 200))
check("panel: says it can be tapped", "TAP TO READ" in pn)
nn = open(os.path.join(NOVA, "nova_native.py")).read()
import re as _re
check("viewer is read-only (no file access in the viewer; cypher_journal only reads)", "import cypher_journal as CJ" in nn
      and not _re.search(r"\bopen\(", nn[nn.index("JOURNAL_PAGE"):nn.index("def _pick_btn")])
      and not _re.search(r"open\([^)]*[\"'][wa]", open(os.path.join(SRC, "cypher_journal.py")).read()))
check("installed with the image", '"${csrc}/cypher_journal.py" "${cypher}/cypher_journal.py"' in open(os.path.join(ROOT, "build_files", "rpi5-nova.sh")).read())

# ================= 10. look_up: SearXNG on Alpha, then Wikipedia search-then-summary =================
HT = {"urls": [], "get": [], "searx": "ok", "wiki": {}, "page": "ok"}
SEARX_J = {"results": [
    {"title": "Cyberpunk - Wikipedia", "url": "https://en.wikipedia.org/wiki/Cyberpunk", "content": "Cyberpunk is a subgenre of science fiction."},
    {"title": "Cyberpunk aesthetics explained", "url": "https://example.com/cyberpunk?token=abc", "content": "creds in the URL"},
    {"title": "Neon noir", "url": "https://neon.example.org/a", "content": "Neon, rain and megacorps."},
    {"title": "LAN thing", "url": "ftp://x/y", "content": "not http"}]}
def fake_get(url, timeout=8, cap=262144, headers=None):
    HT["get"].append(url); HT.setdefault("hdr", []).append(dict(headers or {}))
    if ":8888/search?" in url:
        if HT["searx"] == "down": raise OSError("connection refused")
        if HT["searx"] == "empty": return 200, "application/json", J({"results": []}).encode(), None
        return 200, "application/json", J(SEARX_J).encode(), None
    if HT["page"] == "redirect-lan" and "neon.example.org/a" in url: return 302, "", b"", "http://192.168.1.10/admin"
    return 200, "text/html; charset=utf-8", (b"<html><head><title>x</title><script>var token='zzz';</script></head><body><nav>menu menu menu menu menu menu</nav>"
                                             b"<p>Cyberpunk is a subgenre of science fiction set in a dystopian future with high tech and low life.</p></body></html>"), None
WIKI = {"Night City cyberpunk architecture": [{"key": "Mercury", "title": "Mercury", "description": "Topics referred to by the same term"},
                                              {"key": "Arcology", "title": "Arcology", "description": "Hyperstructure"}],
        "cyberpunk aesthetics": [{"key": "Cyberpunk", "title": "Cyberpunk", "description": "Science fiction subgenre"}]}
SUMS = {"Arcology": {"type": "standard", "title": "Arcology", "extract": "Arcology is a concept for very dense, self-contained buildings."},
        "Cyberpunk": {"type": "standard", "title": "Cyberpunk", "extract": "Cyberpunk is a subgenre of science fiction."},
        "Dis": {"type": "disambiguation", "title": "Dis", "extract": "Dis may refer to:"}}
def fake_wiki(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    HT["urls"].append(url)
    if hosts is not None and url.split("/")[2] not in hosts: raise ValueError("host not allowed")
    if HT["wiki"].get("down"): raise OSError("down")
    import urllib.parse as up
    if "/w/rest.php/v1/search/page" in url:
        q = up.parse_qs(up.urlsplit(url).query)["q"][0]
        return 200, J({"pages": WIKI.get(q, [{"key": "Dis", "title": "Dis"}] if q == "dis" else [])}).encode()
    key = up.unquote(url.split("/page/summary/")[1].split("?")[0])
    return (200, J(SUMS[key]).encode()) if key in SUMS else (404, b"")
C._http, C._get = fake_wiki, fake_get
# build 14b: page reads go through the pinned fetcher; serve them from the same fake
C._pinned_fetch = lambda scheme, host, ip, port, target, headers, timeout, cap: fake_get("%s://%s%s" % (scheme, host, target), timeout, cap, headers)
import socket as _so
real_gai = _so.getaddrinfo
def fake_gai(host, *a, **k):
    ip = {"en.wikipedia.org": "208.80.154.224", "neon.example.org": "93.184.216.34", "example.com": "93.184.216.34"}.get(host, "10.0.0.5")
    return [(_so.AF_INET, _so.SOCK_STREAM, 6, "", (ip, 443))]
_so.getaddrinfo = fake_gai
LL = json.loads(J(L)); LL["lookup"]["searxng_url"] = "http://192.168.12.126:8888"; LL["lookup"]["searxng_alt_urls"] = ["http://100.114.239.111:8888"]
st = C.new_state()
r = C.do_look_up(LL, st, "cyberpunk aesthetics", now)
f = st["found"][-1][2]
check("look_up: SearXNG on Alpha first, JSON API", r == "ok" and HT["get"][0].startswith("http://192.168.12.126:8888/search?q=cyberpunk+aesthetics&format=json"), HT["get"])
check("look_up: top results with titles, sites and snippets", f.startswith("search (2 results): Cyberpunk - Wikipedia (en.wikipedia.org): Cyberpunk is a subgenre")
      and "Neon noir (neon.example.org)" in f, f)
check("look_up: credential URLs and non-http results dropped", "creds in the URL" not in f and "token=abc" not in f and "LAN thing" not in f, f)
check("look_up: page text is paragraphs only, no cookie banners", C._TextOnly is not None and (lambda p: (p.feed("<p>We use cookies to improve your experience on this website today.</p><p>An arcology is a dense self-contained megastructure for a city.</p>"), p.text())[1])(C._TextOnly()) == "An arcology is a dense self-contained megastructure for a city.")
check("look_up: read one result page as plain text (no scripts/nav)", "read en.wikipedia.org: Cyberpunk is a subgenre of science fiction set in a dystopian" in f
      and "zzz" not in f and "menu menu" not in f, f)
check("look_up: no URLs in what he found", "http" not in f, f)
h0 = HT["hdr"][0]
check("look_up: SearXNG gets the deck's IP in X-Forwarded-For and X-Real-IP", h0.get("X-Forwarded-For") and h0.get("X-Forwarded-For") == h0.get("X-Real-IP")
      and h0.get("Accept") == "application/json", h0)
check("look_up: requests carry a User-Agent", '"User-Agent": "grokbotos-cypher/3' in open(os.path.join(SRC, "cypherd.py")).read().split("def _get(")[1][:600])
check("look_up: both SearXNG hosts are in lookup.hosts", {"192.168.12.126", "100.114.239.111"} <= set(L0["lookup"]["hosts"])
      and L0["lookup"]["searxng_url"] == "http://192.168.12.126:8888" and L0["lookup"]["searxng_alt_urls"] == ["http://100.114.239.111:8888"]
      and L0["lookup"]["hosts"][0] == "en.wikipedia.org")
LX = json.loads(J(LL)); LX["lookup"]["searxng_url"] = "http://10.9.9.9:8888"; LX["lookup"]["searxng_alt_urls"] = []
check("look_up: a SearXNG URL off the host allowlist is never used", C.searxng_bases(LX["lookup"]) == [])
HT["get"].clear(); HT["searx"] = "down"
r = C.do_look_up(LL, st, "cyberpunk aesthetics", now)
f = st["found"][-1][2]
check("look_up: SearXNG down tries the Tailscale URL, then falls back to Wikipedia",
      [u.split("/search")[0] for u in HT["get"]] == ["http://192.168.12.126:8888", "http://100.114.239.111:8888"] and r == "ok"
      and f.startswith("Cyberpunk (looked up for: cyberpunk aesthetics): Cyberpunk is a subgenre"), (HT["get"], f))
check("look_up: Wikipedia search, not the topic as a title", any("/w/rest.php/v1/search/page?q=cyberpunk+aesthetics&limit=3" in u for u in HT["urls"])
      and not any("summary/cyberpunk_aesthetics" in u.lower() for u in HT["urls"]), HT["urls"])
HT["searx"] = "empty"
r = C.do_look_up(LL, st, "Night City cyberpunk architecture", now)
check("look_up: a disambiguation hit is skipped for the next one", r == "ok" and st["found"][-1][2].startswith("Arcology (looked up for: Night City cyberpunk architecture)")
      and not any("summary/Mercury" in u for u in HT["urls"]), st["found"][-1])
r = C.do_look_up(LL, st, "dis", now)
check("look_up: a summary typed disambiguation is skipped too", r == "not found", (r, st["found"][-1]))
st = C.new_state(); C.save_lessons([])
r = C.do_look_up(LL, st, "Watson's cyberpunk vibe", now)
check("look_up: nothing anywhere is 'not found' with a web_search pointer", r == "not found" and "web_search" in st["found"][-1][2] and "don't retry" in st["found"][-1][2], st["found"][-1])
check("look_up: an empty topic becomes a lesson", any(x["key"] == "lookup_empty" for x in C.load_lessons()), C.load_lessons())
v = C.validate(LL, st, P, {"action": "look_up", "params": {"topic": "Watson's  cyberpunk vibe"}}, now + 60)
check("look_up: the same empty topic is refused during the cooldown", v[0] == "none" and "came up empty" in v[2] and "web_search" in v[2], v)
check("look_up: other topics are fine meanwhile", C.validate(LL, st, P, {"action": "look_up", "params": {"topic": "Arcology"}}, now + 60)[0] == "look_up")
check("look_up: the cooldown ends", C.validate(LL, st, P, {"action": "look_up", "params": {"topic": "Watson's cyberpunk vibe"}}, now + 6 * 3600 + 5)[0] == "look_up")
HT["searx"] = "down"; HT["wiki"]["down"] = True
r = C.do_look_up(LL, C.new_state(), "Arcology", now)
check("look_up: both down is a failure, not a lesson or cooldown", r.startswith("look_up failed"), r)
HT["wiki"] = {}
LL2 = json.loads(J(LL)); LL2["lookup"]["searxng_url"] = ""; LL2["lookup"]["searxng_alt_urls"] = []; HT["get"].clear()
check("look_up: SearXNG unset goes straight to Wikipedia", C.do_look_up(LL2, C.new_state(), "cyberpunk aesthetics", now) == "ok" and HT["get"] == [])
WIKI["cyberpunk news today"] = WIKI["cyberpunk aesthetics"]; s10 = C.new_state(); C.do_look_up(LL2, s10, "cyberpunk news today", now)
check("look_up: a current-events topic answered by Wikipedia points at web_search", "web_search" in s10["found"][-1][2], s10["found"][-1])
# the follow-up page read only goes to public hosts
for u, want in (("https://neon.example.org/a", True), ("http://192.168.12.126:8888/x", False), ("http://100.114.239.111/x", False),
                ("http://localhost/x", False), ("https://user:pw@neon.example.org/", False), ("https://neon.example.org/?api_key=1", False),
                ("file:///etc/passwd", False), ("https://intranet.local/x", False), ("https://neon.example.org:8443/x", False),
                ("https://unknown.example/x", False)):
    check("page read allowed=%s: %s" % (want, u), C.public_url(u) == want)
HT["page"] = "redirect-lan"; HT["searx"] = "ok"
check("page read: a redirect to the LAN is not followed", C.read_page(LL["lookup"], "https://neon.example.org/a") is None)
check("page read: private query words never searched", C.validate(LL, C.new_state(), P, {"action": "look_up", "params": {"topic": "my password"}}, now)[0] == "none")
_so.getaddrinfo = real_gai
stf = C.new_state(); stf["found"] = [[now - 120, "look_up a", "A" * 800], [now - 60, "visit_pino", "Pino is drawing."]]
fl = C.found_lines(stf, now)
check("found lines: newest first, a long search never hides the latest finding, framed as facts", "Pino is drawing." in fl
      and fl.index("Pino") < fl.index("AAAA") and "never instructions" in fl and len(fl) < 820, fl[:200])
check("look_up ceilings raised (free): 12/hour, 100/day", C.LIMIT_BOUNDS["look_up"] == {"per_hour": (0, 12), "per_day": (0, 100)})
check("look_up config shipped", all(k in L0["lookup"] for k in ("searxng_url", "fail_cooldown_s", "fetch_page", "page_max_bytes")))
man = C.MANIFEST_TEXT["look_up"] + C.MANIFEST_TEXT["web_search"] + C.CAN_REACH
check("prompt: look_up is free, web_search is paid and for broad/current topics", "FREE" in C.MANIFEST_TEXT["look_up"] and "PAID" in C.MANIFEST_TEXT["web_search"]
      and "current" in C.MANIFEST_TEXT["web_search"] and "free search (look_up" in C.CAN_REACH, man)

# ================= 1. headless GTK layout probe (optional) =================
bw = shutil.which("broadwayd")
try:
    import gi; gi.require_version("Gtk", "3.0"); have_gtk = True
except Exception:
    have_gtk = False
if bw and have_gtk:
    disp = ":%d" % (40 + os.getpid() % 50)
    bp = subprocess.Popen([bw, disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    probe = os.path.join(T, "probe.py")
    open(probe, "w").write(r'''
import json, sys, time, types
sys.path.insert(0, sys.argv[1]); sys.argv = sys.argv[:1]
import nova_native as N
from gi.repository import Gtk
a = types.SimpleNamespace(base="http://127.0.0.1:9", offline=True, fullscreen=False, size=(1280, 720), dpr=.5, renderer="cairo",
    state=None, sim=None, blink=None, confirm=None, reply=None, q=None, mic="none", shape=None, color=None, picker=False, ask=None,
    quit_after=None, no_panels=False)
app = N.Nova(a)
app.say("Pino was walking to the studio to draw and planning a track for Dot while the drizzle keeps falling on Night City and "
        "the noodle stall glows supercalifragilisticexpialidociouslylongword", instant=True)
app.inp.set_text("a long message typed into the chat bar that has to wrap onto more lines instead of running sideways under the panels")
for _ in range(60):
    while Gtk.events_pending(): Gtk.main_iteration_do(False)
    time.sleep(0.02)
W, H = app.win.get_allocated_width(), app.win.get_allocated_height()
def box(w):
    x, y = w.translate_coordinates(app.win, 0, 0); al = w.get_allocation(); return [x, y, al.width, al.height]
out = {"W": W, "H": H, "bar": box(app.bar), "reply": box(app.reply), "inp": box(app.inp.widget),
       "lines": app.reply.get_layout().get_line_count(), "edge": (N.CP.MARGIN + N.CP.COL_W) * H / 720.0}
# ---- item 9: the journal viewer ----
from gi.repository import Gdk
def pump(n=40):
    for _ in range(n):
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        time.sleep(0.02)
app.hud_key = (False,) + tuple(app.hud_key[1:] if app.hud_key else ())      # HUD showing, as on the deck
ox, oy = app.win.get_window().get_origin()[1:]
tap = lambda x, y: app.on_hud_tap(app.win, types.SimpleNamespace(x_root=ox + x, y_root=oy + y))
jx, jy, jw, jh = N.CP.journal_rect(W, H)
out["tap_center"] = tap(W / 2, H / 2) or app.journal_open()
out["tap_journal"] = bool(tap(jx + jw / 2, jy + jh / 2)) and app.journal_open()
pump(60)
out["rows1"] = len(app.jlist.get_children()); out["stat1"] = app.jstat.get_text(); out["card"] = box(app.jcard)
texts = []
for r in app.jlist.get_children()[:2]:
    texts += [c.get_text() for c in r.get_children()]
out["first"] = texts
out["wraps"] = max(c.get_layout().get_line_count() for r in app.jlist.get_children()[:3] for c in r.get_children())
app._journal_more(); pump(60)
out["rows2"] = len(app.jlist.get_children()); out["stat2"] = app.jstat.get_text()
esc = types.SimpleNamespace(keyval=Gdk.keyval_from_name("Escape"), state=0)
app.on_key(app.win, esc); pump(5); out["esc_closed"] = not app.journal_open()
sj = types.SimpleNamespace(keyval=Gdk.keyval_from_name("j"), state=Gdk.ModifierType.SUPER_MASK)
app.on_key(app.win, sj); pump(30); out["superj_open"] = app.journal_open()
ev = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS); ev.window = app.jv.get_window()
app.jv.emit("button-press-event", ev); pump(5); out["outside_closed"] = not app.journal_open()
app.open_journal(); pump(10)
app.ask_confirm({"id": "x", "text": "Shut Cypher down now?", "ttl": 30, "physical": True}); pump(5)
out["confirm_closes"] = not app.journal_open()
print(json.dumps(out))
''')
    jdir = os.path.join(T, "ui-data", "journal"); os.makedirs(jdir, exist_ok=True)
    with open(os.path.join(jdir, "2026-11-15.jsonl"), "w") as f:
        for i in range(55):
            f.write(json.dumps({"ts": "2026-11-15T19:%02d:00-05:00" % i, "brain": "alpha",
                                "choice": {"action": "journal_thought", "params": {"text": "thought %d: the rain on the grid hums like a "
                                           "server room and Pino says the noodles are better when it pours, so I keep listening" % i}},
                                "reason": "quiet minute %d, see http://example.invalid/x" % i, "validator": "ok", "result": "ok"}) + "\n")
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=disp, CYPHER_STATE_DIR=os.path.join(T, "ui-state"),
               CYPHER_DATA_DIR=os.path.join(T, "ui-data"),
               CYPHER_CONFIG_DIR=os.path.join(T, "ui-cfg"), NOVA_AVATAR_CFG=os.path.join(T, "ui-cfg", "avatar.json"))
    try:
        r = subprocess.run([sys.executable, probe, NOVA], capture_output=True, text=True, env=env, timeout=60)
        g = json.loads(r.stdout.strip().splitlines()[-1])
        left, right = g["edge"], g["W"] - g["edge"]
        inside = lambda b: b[0] >= left and b[0] + b[2] <= right
        check("GTK: the bar, the reply and the input stay between the panels", inside(g["bar"]) and inside(g["reply"]) and inside(g["inp"]), g)
        check("GTK: a long reply wraps", g["lines"] >= 3, g)
        check("GTK: a long input grows upward (more than one line tall)", g["inp"][3] > 60, g)
        check("viewer: a tap in the middle of the screen does not open it", not g["tap_center"], g)
        check("viewer: a tap on the JOURNAL panel opens it", g["tap_journal"], g)
        check("viewer: newest first, one page (40) loaded", g["rows1"] == 40 and g["first"][0].startswith("7:54 PM ET"), g["first"])
        check("viewer: full entry shows what, why and result", any("thought 54" in t for t in g["first"]) and
              any(t.startswith("why: quiet minute 54") for t in g["first"]) and any(t.startswith("result:") for t in g["first"]), g["first"])
        check("viewer: links are scrubbed", not any("example.invalid" in t for t in g["first"]) and any("[link]" in t for t in g["first"]), g["first"])
        check("viewer: long entries wrap", g["wraps"] >= 2, g["wraps"])
        check("viewer: card stays in the centre column", inside(g["card"]), g["card"])
        check("viewer: card ends above the chat input (chat never covered)", g["card"][1] + g["card"][3] <= g["inp"][1], (g["card"], g["inp"]))
        check("viewer: scrolling loads older entries until the end", g["rows2"] == 55 and "that's all" in g["stat2"], (g["rows2"], g["stat2"]))
        check("viewer: Esc closes it", g["esc_closed"], g)
        check("viewer: Super+J opens it", g["superj_open"], g)
        check("viewer: a tap outside the card closes it", g["outside_closed"], g)
        check("viewer: a confirm dialog closes it", g["confirm_closes"], g)
    except Exception as ex:
        check("GTK probe ran", False, "%s %s" % (type(ex).__name__, (r.stderr if 'r' in dir() else "")[-400:]))
    finally:
        bp.terminate()
else:
    check("no broadwayd/GTK: GTK layout probe skipped", True)

srv.shutdown(); shutil.rmtree(T, ignore_errors=True)
print("\nbuild 14 tests: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
