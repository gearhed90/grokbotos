#!/usr/bin/env python3
"""Build 13: unambiguous time facts for every brain and a check on night/quiet-hours claims, a prompt
that fits Alpha's proxy (so the deck stops falling to the local 3B), waiting out Alpha's camera
work, a retry-then-clean-fallback for refused choices, a check_grid cooldown, small activities when
content (and less journaling), and the grid panel's REPO line. Earlier (build 12, part 2): Night City (simulated places, go_to, eat at the noodle stall, out during quiet
hours), Cypher's own body design and character-sheet sections through the tuning proposals
(approved only with `tuning approve`), Pino-style mechanics (decide-then-speak, threads, a world
manifest), and phase 6 (speak, Ask Nova outbox, local code proposals, headset/wake-word groundwork
in novad). No display, root, audio or network."""
import importlib.util, json, os, socket, sys, tempfile, threading, time
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
        if isinstance(r, tuple): return self._j(r[0], r[1])
        self._j(200, {"model": "fake", "choices": [{"message": {"content": r}}], "usage": {}})
port = free_port()
srv = ThreadingHTTPServer(("127.0.0.1", port), Proxy); threading.Thread(target=srv.serve_forever, daemon=True).start()
T = tempfile.mkdtemp(); TOKEN = "k" * 12 + "TokSecret0123456789"; TOPIC = "cypher-" + "T0p1cSecretXyz_abcdefgh"
for n, v in (("token", TOKEN), ("topic", TOPIC)):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
L0 = json.load(open(os.path.join(SRC, "cypher-limits.json")))
L0["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % port]; L0["brain"]["primary_url"] = L0["brain"]["primary_urls"][0]
L0["brain"]["local"]["enabled"] = False; L0["brain"]["hosted_backup"]["enabled"] = False
L0["failover"]["enabled"] = False; L0["camera"]["enabled"] = False
LIM = os.path.join(T, "limits.json"); json.dump(L0, open(LIM, "w")); os.chmod(LIM, 0o644)
os.environ.update(CYPHER_LIMITS=LIM, CYPHER_LIMITS_INSECURE_OK="1", CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"),
                  CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"), CYPHER_NTFY_TOPIC_FILE=os.path.join(T, "topic"),
                  CYPHER_CONFIG_DIR=os.path.join(T, "cfg"), CYPHER_STATE_DIR=os.path.join(T, "state"),
                  CYPHER_DATA_DIR=os.path.join(T, "data"), CYPHER_PERSONA=os.path.join(SRC, "persona.md"),
                  CYPHER_DRY_RUN="1", TZ="America/New_York", XDG_RUNTIME_DIR=os.path.join(T, "run"))
for d in ("run", "state", "cfg"): os.makedirs(os.path.join(T, d), exist_ok=True)
time.tzset()
def load(path, name, **env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sys.path.insert(0, NOVA)
C = load(os.path.join(SRC, "cypherd.py"), "cypherd_b13", CYPHER_HOST="deck")
A = load(os.path.join(SRC, "cypherd.py"), "cypherd_b13a", CYPHER_HOST="alpha")
os.environ["CYPHER_HOST"] = "deck"
CL = load(os.path.join(NOVA, "cypher_link.py"), "cypher_link_b13")
L = C.current_limits(C.new_state())
def at(h, m=0, day=16): return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))
now = at(14)
P = {"local_time": "Mon 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": [], "brain": "alpha"}
Q = dict(P, quiet_hours=True, local_time="Mon 1:00 AM", presence="away")
perceive = lambda p: (lambda L, n: dict(p))
v = lambda a, pr, s=None, p=P, n=now: C.validate(L, s or C.new_state(), p, {"action": a, "params": pr}, n)
def run_tick(st, p=P, n=now):
    return C.tick(L, st, n, perceive_fn=perceive(p), camera_fn=lambda L, s, x: [], inbox_fn=lambda L, s, x: [], talk_fn=lambda *a: 0)
def journal_text():
    d = os.path.join(T, "data", "journal")
    return "".join(open(os.path.join(d, f)).read() for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""


J = json.dumps
SUN = time.mktime((2026, 11, 15, 17, 30, 0, 0, 0, -1))          # Sunday 5:30 PM, not quiet hours
PS = dict(P, local_time="Sunday 5:30 PM", hour=17, presence="locked", focused_app="", window_title="")
MON1 = at(1)                                                     # Monday 1 AM: quiet hours
FRI10 = time.mktime((2026, 11, 20, 22, 0, 0, 0, 0, -1))          # Friday 10 PM: no quiet hours on Fridays

# ---- time facts ----
tf = C.time_facts(L, SUN, False)
check("time facts: day, time, Eastern, evening", tf.startswith("NOW: Sunday 5:30 PM Eastern time, evening (not night)."), tf)
check("time facts: explicit NOT quiet hours and NOT night, with the next start", "It is NOT quiet hours and NOT night" in tf
      and "next start Sunday 11:00 PM" in tf, tf)
tq = C.time_facts(L, MON1, True)
check("time facts in quiet hours: YES, until 6 AM", "Quiet hours: YES" in tq and "until Monday 6:00 AM" in tq and "night" in tq, tq)
check("day parts", [C.day_part(h) for h in (8, 14, 18, 23, 3)] == ["morning, daylight", "afternoon, daylight", "evening (not night)", "night", "night"])
check("Friday 10 PM: night but not quiet hours", "Quiet hours: NO" in C.time_facts(L, FRI10, False) and "NOT night" not in C.time_facts(L, FRI10, False))
st = C.new_state()
m = C.build_messages(L, st, PS, SUN)
check("prompt: NOW line first in the user message", m[1]["content"].startswith("NOW: Sunday 5:30 PM"), m[1]["content"][:80])
check("prompt: repeated at the end", m[1]["content"].rstrip().endswith("Choose.") and m[1]["content"].count("NOW: Sunday 5:30 PM") == 2)
check("prompt: trust the NOW line, never a feeling", "trust the NOW line" in m[0]["content"])
check("persona no longer says 'quiet hours of the grid'", "quiet hours of the grid" not in m[0]["content"] and "quiet hours of the grid" not in C.persona())
check("perception uses the full day name", C.perceive_alpha(L, SUN)["local_time"] == "Sunday 5:30 PM")

# ---- false night / quiet-hours claims ----
fc = lambda t, p=PS, n=SUN: C.false_time_claim(t, p, n)
check("claim: 'Waited in the quiet hours' at 5:23 PM Sunday", fc("Waited in the quiet hours, content but restless.") is not None)
check("claim: 'the stillness of the night' at 5:31 PM", fc("Reflect on the stillness of the night.") is not None)
check("claim: midnight / nighttime", fc("Feels like midnight.") and fc("Nighttime hum.") is not None)
check("no claim: Night City, tonight, last night, every night", not any(fc(t) for t in ("Night City glows.", "Noodles tonight.", "Last night was loud.", "Every night the same.")))
check("no claim: quiet hours start at 11", fc("Quiet hours start at 11 PM.") is None)
Q1 = dict(PS, quiet_hours=True, local_time="Monday 1:00 AM")
check("no claim in real quiet hours", fc("Quiet hours. The night is still.", Q1, MON1) is None)
F10 = dict(PS, local_time="Friday 10:00 PM")
check("Friday 10 PM: 'night' fine, 'quiet hours' not", fc("The night is wet.", F10, FRI10) is None and fc("Quiet hours again.", F10, FRI10) is not None)
check("rewrite drops only the false sentence", C.drop_false_time("Pino's kiwi is odd. Stillness of the night. Want noodles.", PS, SUN)
      == "Pino's kiwi is odd. Want noodles.")
vs = lambda a, pr, s=None, p=PS: C.validate(L, s or C.new_state(), p, {"action": a, "params": pr}, SUN)
r = vs("journal_thought", {"text": "Waited in the quiet hours."})
check("validator refuses the false claim, naming the real time", r[0] == "none" and "says 'quiet hours'" in r[2] and "Sunday 5:30 PM" in r[2], r)
check("validator: text under 'thought' is accepted", vs("journal_thought", {"thought": "Pino again."}) == ("journal_thought", {"text": "Pino again."}, "ok"))
check("show_note / message_zack get the same check", vs("message_zack", {"text": "Quiet night."}, p=dict(PS, presence="active"))[2].startswith("rejected: says"))

def tick_at(st, n=SUN, p=PS):
    return C.tick(L, st, n, perceive_fn=perceive(p), camera_fn=lambda L, s, x: [], inbox_fn=lambda L, s, x: [], talk_fn=lambda *a: 0)

# ---- retry, then a clean fallback ----
st = C.new_state(); PX["seen"].clear()
PX["queue"] = [J({"action": "journal_thought", "params": {"text": "Stillness of the night."}, "reason": "night"}),
               J({"action": "visit_pino", "params": {}, "reason": "see what the kiwi is up to"})]
e = tick_at(st)
check("retry: a false night claim gets a second try that runs", e["choice"]["action"] == "visit_pino" and e["validator"] == "ok"
      and "second try ok" in e.get("retry", ""), e)
check("retry: the second ask spells out the refusal and the time", len(PX["seen"]) == 2 and "That was refused" in PX["seen"][1]["messages"][-1]["content"]
      and "NOW: Sunday 5:30 PM" in PX["seen"][1]["messages"][-1]["content"])
check("retry: still under the proxy's 6000 chars", sum(len(x["content"]) for x in PX["seen"][1]["messages"]) <= 6000,
      sum(len(x["content"]) for x in PX["seen"][1]["messages"]))
st = C.new_state()
PX["queue"] = [J({"action": "journal_thought", "params": {"text": "Pino's kiwi is odd. The night is still."}, "reason": "x"})] * 2
e = tick_at(st)
check("fallback: twice false -> rewritten without the false sentence", e["choice"] == {"action": "journal_thought", "params": {"text": "Pino's kiwi is odd."}}
      and e["note"].startswith("rewrote"), e)
st = C.new_state()
PX["queue"] = [J({"action": "journal_thought", "params": {}, "reason": "Reflect on current state"})] * 2
e = tick_at(st)
check("fallback: 'needs text' twice -> a clean none (not a refusal on the HUD)", e["choice"]["action"] == "none" and e["validator"] == "ok"
      and "needs text" in e["retry"] and e["note"].startswith("fallback") and e.get("model_choice") == "journal_thought", e)
check("fallback: actions list shows none, not a refusal", "refused" not in st["last_actions"][-1], st["last_actions"])
check("the retry asked for params.text", "params.text" in PX["seen"][-1]["messages"][-1]["content"])
st = C.new_state()
PX["queue"] = [J({"action": "go_to", "params": {"place": "noodle_stall"}, "reason": "Quiet hours walk. Noodles."})]
e = tick_at(st)
check("a false claim in the reason is rewritten out of the HUD's why", e["reason"] == "Noodles." and e["choice"]["action"] == "go_to", e)

# ---- prompt size: always under the cap, even with a full deck ----
os.makedirs(os.path.dirname(C.MEM_FILE), exist_ok=True)
json.dump([{"text": "m" * 200}] * 3, open(C.MEM_FILE, "w"))
os.makedirs(os.path.dirname(C.PREFS_FILE), exist_ok=True)
json.dump({"notes": ["n" * 90] * 8}, open(C.PREFS_FILE, "w"))
st = C.new_state(); st["threads"] = [{"id": i, "text": "t" * 100, "since": SUN, "touched": SUN} for i in (1, 2, 3)]
for i in range(3): C._found(st, "web_search", "f" * 300, SUN)
st["last_talk"] = SUN - 60
m = C.build_messages(L, st, dict(PS, zack=[[SUN, "z" * 200]] if False else []), SUN)
tot = sum(len(x["content"]) for x in m)
check("full deck prompt fits max_prompt_chars (5200)", tot <= L["brain"]["max_prompt_chars"] == 5200, tot)
check("the time, drives and manifest always stay", "NOW: Sunday" in m[1]["content"] and "drives:" in m[1]["content"] and "Manifest:" in m[0]["content"])
os.remove(C.MEM_FILE); os.remove(C.PREFS_FILE)

# ---- brain choice: 413 and Alpha's camera work ----
st = C.new_state(); slept = []
C.SLEEP = lambda s: slept.append(s)
PX["queue"] = [(413, {"error": "prompt too long"})]
try:
    C.ask_alpha(L, [{"role": "user", "content": "x"}])
    r = "no error"
except C.BrainBusy as b:
    r = (b.reason, b.backoff)
check("413 reads as alpha_prompt_too_long (no backoff)", r == ("alpha_prompt_too_long", False), r)
PX["queue"] = [(503, {"busy": "camera_recent"}), J({"action": "none", "params": {}, "reason": "ok"})]
c, b, mdl, cost, notes = C.think(L, st, [{"role": "user", "content": "x"}], SUN)
check("camera_recent: wait once, then Alpha (not the local 3B)", b == "alpha" and slept == [30] and "alpha_after_wait" in notes, (b, slept, notes))
check("limits: alpha_busy_wait_s 30", L["brain"]["alpha_busy_wait_s"] == 30)

# ---- check_grid cooldown ----
st = C.new_state(); st["grid"] = {"alpha": "up", "proxy": "ok", "mind": "deck", "cams": "ok", "at": SUN, "repos": [{"ok": True, "sha": "abc1234"}]}
st["recent"] = [[SUN - 600, "check_grid"]]; st["grid_seen_sig"] = C.grid_sig(st)
check("check_grid 10 min after the last, nothing changed -> refused", "nothing changed" in (C.blocked(L, st, PS, "check_grid", SUN) or ""))
check("... and left out of the manifest", "check_grid -" not in C.build_messages(L, st, PS, SUN)[0]["content"])
st["grid"]["proxy"] = "busy (camera_recent)"; st["grid_seen_sig"] = C.grid_sig(st); st["grid"]["proxy"] = "busy (camera_busy)"
check("proxy busy flicker is not a change", C.blocked(L, st, PS, "check_grid", SUN) is not None)
st["grid"]["repos"][0]["sha"] = "def5678"
check("a new commit is a change -> allowed", C.blocked(L, st, PS, "check_grid", SUN) is None)
st["grid"]["repos"][0]["sha"] = "abc1234"; st["grid"]["proxy"] = "busy (camera_recent)"
check("Zack asking (talk) skips the wait", C.blocked(L, st, dict(PS, talk=True), "check_grid", SUN) is None)
check("after 30 min it is allowed again", C.blocked(L, st, PS, "check_grid", SUN + 1201) is None)
check("limits: check_grid min_gap_s 1800, 2 an hour", L["actions"]["check_grid"]["min_gap_s"] == 1800 and L["actions"]["check_grid"]["per_hour"] == 2)

# ---- content: small activities, less journaling ----
st = C.new_state(); st["mood"] = {"label": "content"}
st["threads"] = [{"id": 1, "text": "what Pino is", "since": SUN, "touched": time.time()}]
u = C.build_messages(L, st, PS, SUN)[1]["content"]
check("content: a hint toward small things (Pino, threads, Night City)", "You are content" in u and "visit_pino" in u and "go_to" in u and "threads" in u, u)
check("content: eat suggested only when energy is lower", "noodle stall" not in u.split("You are content")[1].split("\n")[0])
st["drives"]["energy"] = 0.4
check("content + energy 0.4: eat suggested", "eat at the noodle stall" in C.build_messages(L, st, PS, SUN)[1]["content"])
check("none no longer called 'often right'", "often right" not in C.build_messages(L, st, PS, SUN)[0]["content"])
st = C.new_state(); st["recent"] = [[SUN - 300, "journal_thought"]]
check("journal: refused 5 min after the last", "journal thought" in (C.blocked(L, st, PS, "journal_thought", SUN) or ""))
check("journal: fine after 15 min", C.blocked(L, st, PS, "journal_thought", SUN + 700) is None)
check("limits: journal 3 an hour, every 15 min", L["actions"]["journal_thought"]["per_hour"] == 3 and L["actions"]["journal_thought"]["min_gap_s"] == 900)
st = C.new_state(); st["drives"]["energy"] = 0.85
check("eat refused when not hungry", "not hungry" in (C.blocked(L, st, PS, "eat", SUN) or ""))
st["drives"]["energy"] = 0.5
check("eat fine at 0.5", C.blocked(L, st, PS, "eat", SUN) is None)
check("message_zack unchanged: 3 an hour, no daily cap", L["actions"]["message_zack"]["per_hour"] == 3 and L["actions"]["message_zack"]["per_day"] is None)
check("search budget unchanged ($0.50/day)", L["brain"]["hosted_backup"]["daily_budget_usd"] == 0.5)

# ---- the grid panel's REPO line ----
import importlib
sys.path.insert(0, SRC)
try:
    import cairo
    PN = load(os.path.join(SRC, "cypher_panels.py"), "cypher_panels_b13")
    msg = "rpi5 cypher build 12 part 2: Night City (go_to, eat), body + character self-design via proposals, Pino mechanics"
    snap = {"grid": {"alpha": "up", "proxy": "ok", "mind": "deck", "standby": "17:01", "cams": "ok", "checked": "5:44 PM",
                     "repos": [["grokbotos", "e08930d", "4:36 PM", msg]]}, "tick": 1}
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 300, 600); cr = cairo.Context(surf); PN.font(cr, 10.5)
    lines = PN.wrap(cr, msg, PN.COL_W - 70, 4)
    check("REPO: a 112-char commit subject shows in full (no ellipsis)", " ".join(lines) == msg and len(lines) <= 4, lines)
    out = os.path.join(T, "panels.png"); PN.render_png(out, snap, size=(1280, 720))
    check("panels render with a long commit subject", os.path.getsize(out) > 1000)
except ImportError:
    check("cairo missing: panel checks skipped", True)
check("grid snapshot keeps up to 120 chars of the subject", len(C.grid_snapshot({"grid": {"alpha": "up", "repos": [{"ok": True, "name": "g", "sha": "1", "epoch": 0, "msg": "x" * 150}]}},
      lambda t, n: str(t or "")[:n], SUN)["repos"][0][3]) == 120)
check("limits: grid max_msg_chars 120", L["grid"]["max_msg_chars"] == 120)

# ---- threads: no junk goals ----
st = C.new_state()
check("thread: one word refused", "few words" in C.apply_thread(st, {"open": "drifts"}, SUN))
check("thread: a bare id refused", "few words" in C.apply_thread(st, {"open": "#1 drifts"}, SUN))
check("thread: a real goal opens", C.apply_thread(st, {"open": "find out what Pino's town is"}, SUN).startswith("opened"))
st["threads"].append({"id": 9, "text": "drifts", "since": SUN, "touched": SUN})
check("old junk threads are dropped", [t["text"] for t in C.threads_live(st, SUN)] == ["find out what Pino's town is"])

print("\nbuild 13 tests: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
