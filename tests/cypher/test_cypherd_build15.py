#!/usr/bin/env python3
"""Build 15: the mind (habituation, fear of being predictable, evidence-weighted beliefs, open loops, a small
working memory, the library on Alpha), the lore codex, Pino's API on his clock, interviews, the slim prompt,
feature flags, the migration and the hand-off of the new state. No root, network or display: Alpha's library
runs in-process (tools/cypher-alpha/proxy/cypher_library.py), pinos.world and SearXNG are mocked."""
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
A = load(os.path.join(SRC, "cypherd.py"), "cypherd_b15a", CYPHER_HOST="alpha")
os.environ["CYPHER_HOST"] = "deck"
L = C.current_limits(C.new_state())
def at(h, m=0, day=16): return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))
now = at(14)
P = {"local_time": "Monday 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": [], "brain": "alpha"}
Q = dict(P, quiet_hours=True, local_time="Monday 1:00 AM", presence="away")
J = json.dumps
perceive = lambda p: (lambda L, n: dict(p))


sys.path.insert(0, os.path.join(ROOT, "tools", "cypher-alpha", "proxy"))
import cypher_library as CLIB
LIB = CLIB.Library(os.path.join(T, "library"))
LIBCALLS = []
def fake_alpha_api(L_, method, path, body=None, timeout=6):
    import urllib.parse as up
    LIBCALLS.append((method, path))
    u = up.urlsplit(path); q = dict(up.parse_qsl(u.query))
    if u.path == "/library/add": return 200, {"added": LIB.add(body["entries"], body.get("holder"))}
    if u.path == "/library/touch": return 200, {"touched": LIB.touch(body["ids"])}
    if u.path == "/library/search": return 200, {"entries": LIB.search(q.get("q", ""), int(q.get("limit", 3)))}
    if u.path == "/library/wander": return 200, {"entries": LIB.wander(q.get("mode", "random"), int(q.get("limit", 2)))}
    if u.path == "/library/stats": return 200, LIB.stats()
    return 404, {}
C.alpha_api = fake_alpha_api
def reset_mind():
    shutil.rmtree(C.MIND_DIR, ignore_errors=True)
    for f in (C.PINO_CACHE, C.FEATURES_FILE):
        if os.path.exists(f): os.remove(f)

# ================= 1. feature flags =================
check("every feature on by default except pino_post", all(C.feature(L, f) for f in C.FEATURES if f != "pino_post") and not C.feature(L, "pino_post"))
check("the shipped limits carry the features block", L0["features"]["pino_post"] is False and set(C.FEATURES) <= set(L0["features"]))
C.set_feature("lore", False); check("features.json turns one off", not C.feature(L, "lore"))
C.set_feature("lore", None); check("default clears the override", C.feature(L, "lore"))
C.set_feature("pino_post", True); check("pino_post cannot be turned on from features.json", not C.feature(L, "pino_post"))
check("CLI refuses the locked flag", C.cli_features(["on", "pino_post"]) == 1)
reset_mind()
check("visit_pinos_world capped once a day and once a week", L0["actions"]["visit_pinos_world"]["per_week"] == 1 and L0["actions"]["visit_pinos_world"]["per_day"] == 1)
check("visit_pino 30 min apart (shipped and default)", L0["actions"]["visit_pino"]["min_gap_s"] == 1800)

# ================= 2. habituation and the fear of being predictable =================
st = C.new_state()
f0 = C.habit_factor(L, st, "go_to", {"place": "noodle_stall"}, now)
check("fresh move gives a little more (1.25)", f0 == 1.25, f0)
for i in range(4): C.note_key(st, "go_to", {"place": "noodle_stall"}, now - 600 * (4 - i))
f1 = C.habit_factor(L, st, "go_to", {"place": "noodle_stall"}, now)
check("the same move again gives much less", f1 < 0.45, f1)
d, f = C.habit_effect(L, st, "go_to", {"place": "noodle_stall"}, C.load_tunables(L), now)
check("stale move: relief scaled down and a little duller", f < 0.45 and d.get("boredom", 0) > C.ACTION_EFFECTS["go_to"]["boredom"], d)
check("after a few hours it recovers", C.habit_factor(L, st, "go_to", {"place": "noodle_stall"}, now + 8 * 3600) > 0.8)
check("eat and rest never wear thin", C.habit_factor(L, st, "eat", {}, now) == 1.0 and C.habit_factor(L, st, "rest", {}, now) == 1.0)
st = C.new_state()
for i in range(10): C.note_key(st, "go_to", {"place": "apartment" if i % 2 else "noodle_stall"}, now - 300 * (10 - i))
pr = C.predictability(st, now)
check("apartment <-> noodle stall pacing reads as predictable", pr and pr["score"] >= C.PREDICTABLE_AT and pr["alternating"], pr)
hl = C.habit_lines(L, st, C.allowed_actions(L), now)
check("the prompt names the rut and the fear", "predictable" in hl and "back and forth" in hl, hl)
b0 = st["drives"]["boredom"]; C.fear_step(L, st, now, 0.25)
check("the rut is uncomfortable: boredom climbs with time", abs(st["drives"]["boredom"] - min(1, b0 + 0.075)) < 1e-6)
st2 = C.new_state(); [C.note_key(st2, a, {}, now - 60 * i) for i, a in enumerate(("look_up", "library", "research_lore", "browse", "visit_pino", "review_lessons"))]
check("varied moves are not predictable", C.predictability(st2, now)["score"] < C.PREDICTABLE_AT)

# ================= 3. beliefs from outcomes =================
reset_mind()
for i in range(3): C.belief_update(L, None, "go_to", {"place": "noodle_stall"}, 0.0, True, now + i)
for i in range(3): C.belief_update(L, None, "research_lore", {}, 0.05, True, now + i)
bl = C.belief_lines(L, now + 10)
check("beliefs weigh evidence per outcome", "Walking to noodle stall does little for me (0 for, 3 against)" in bl and "Researching lore lifts me (3 for, 0 against)" in bl, bl)
C.add_lesson("time_claim", "Trust the NOW line: never say night unless it says so.", "validator", now)
check("a lesson becomes a rule belief", any(r["key"] == "rule:time_claim" for r in C.load_beliefs()) and "lessons (from your own mistakes)" in C.belief_lines(L, now + 10))

# ================= 4. open loops =================
st = C.new_state()
r = C.apply_loop(L, st, {"open": "finish the Arasaka codex entry", "kind": "work"}, now)
check("open a loop", r.startswith("opened loop #1 (work)"), r)
C.apply_loop(L, st, {"open": "learn the noodle cook's name", "kind": "question"}, now)
C.apply_loop(L, st, {"open": "map the street below at night", "kind": "want"}, now)
check("the budget is spent (3 banked)", C.loop_budget(st, now) < 1)
r = C.apply_loop(L, st, {"open": "a fourth thing to chase", "kind": "want"}, now)
check("no budget: the first refusal says so once", r == "loop not opened: no room (close one first)", r)
check("...then it is quiet (no every-tick refusal)", C.apply_loop(L, st, {"open": "a fifth thing to chase", "kind": "want"}, now + 60) is None)
check("the budget refills over time", C.loop_budget(st, now + 3 * 3600 + 5) >= 1)
r = C.apply_loop(L, st, {"close": 2, "note": "his name is Kenji"}, now + 100)
check("close a loop", r.startswith("closed loop #2"), r)
check("not judged right away", C.to_judge(st, now + 200) == [])
check("judgeable after 2 h, and the prompt asks", C.to_judge(st, now + 2 * 3600 + 200) and "look back (reflect)" in C.loop_lines(L, st, now + 2 * 3600 + 200))
v = C.validate(L, st, P, {"action": "reflect", "params": {"id": 2, "verdict": "worth it, now I can greet him"}}, now + 2 * 3600 + 300)
check("reflect validates", v[2] == "ok", v)
check("reflect records the verdict", C.do_reflect(L, st, {"id": 2, "verdict": "worth it"}, now + 2 * 3600 + 300) == "ok"
      and st["loops_closed"][-1]["verdict"] == "worth it")
check("untouched loops expire after 12 h", C.loops_live(L, st, now + 13 * 3600) == [] and any(c["how"] == "expired" for c in st["loops_closed"]))
check("the thread cap message never appears with loops on", "thread refused" not in json.dumps(st))

# ================= 5. working memory and the library =================
reset_mind(); st = C.new_state()
for i in range(C.WM_CAP + 3):
    C.wm_add(L, st, "memory number %d about the neon rain in Watson" % i, "memory", now - 86400 * (C.WM_CAP + 3 - i), strength=1.0)
wm = C.load_wm()
check("working memory stays small", len(wm) == C.WM_CAP, len(wm))
check("the weakest (oldest) went to the library outbox", len(C.library_outbox()) == 3 and "memory number 0" in C.library_outbox()[0]["text"])
hits = C.wm_recall_from(L, "thinking about neon rain in Watson again", now)
check("recall strengthens what it echoes", hits and max(r["strength"] for r in C.load_wm()) >= 2.0)
n = C.library_flush(L, st, now=now)
check("outbox flushed to Alpha's library", n == 3 and LIB.stats()["total"] == 3 and C.library_outbox() == [])
C.library_add(L, st, "I wrote about Arasaka Tower in the rain", "journal", now - 5 * 86400, item={"ts": now - 5 * 86400})
st["place"] = "apartment"; st["mood"] = C.mood(st["drives"])
c0 = st["drives"]["curiosity"]
r = C.execute("library", {"query": "Arasaka"}, L, st, P)
check("library search finds an old page", r == "ok (rediscovered something old)" and "Arasaka" in st["found"][-1][2], (r, st["found"][-1:]))
check("he is at the library now", st["place"] == "library" and "library" in C.world_places(L))
check("a rediscovery returns to working memory", any("Rediscovered" in w["text"] for w in C.load_wm()))
check("finding something forgotten feels good", st["drives"]["curiosity"] < c0)
r = C.execute("library", {}, L, st, P)
check("wandering the stacks works", r.startswith("ok"), r)
check("library unreachable -> closed, not a crash", (lambda: (setattr(C, "alpha_api", lambda *a, **k: (_ for _ in ()).throw(C.BrainBusy("x"))),
      C.execute("library", {"query": "x"}, L, C.new_state(), P))[1])() == "library closed (Alpha unreachable)")
C.alpha_api = fake_alpha_api

# ================= 6. Pino's API on his clock =================
reset_mind()
PCALLS = []
PINO = {"code": 200}
def fake_http(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    PCALLS.append(url)
    if PINO["code"] == 503: return 503, b"{}"
    part = url.split("/api/v1/")[1].split("?")[0]
    body = {"now": {"asleep": False, "doing": "tending the tea garden", "thought": "the kettle sings", "feeling": {"mood": 0.4, "energy": 0.2},
                    "world": {"day": 4400}},
            "feed": {"entries": [{"at": 1, "kind": "act", "text": "watered the ferns", "why": "they looked thirsty"}]},
            "mind": {"loudest": [{"kind": "want", "subject": "a new song"}], "open": {"wants": 2}},
            "memories": {"beliefs": [{"text": "mornings are kind", "evidence": 7}]},
            "who": {"traits": ["patient"]}}[part]
    return 200, json.dumps(body).encode()
C._http = fake_http
st = C.new_state()
r = C.do_visit_pino_api(L, st, now)
f = st["found"][-1][2]
check("visit reads now + feed + one deeper part", r == "ok" and len(PCALLS) == 3 and any("/mind" in u for u in PCALLS), PCALLS)
check("credited to Pino, his words quoted, never as Cypher's", "Pino, from pinos.world" in f and "not yours" in f and '"the kettle sings"' in f, f)
PCALLS.clear(); C.do_visit_pino_api(L, st, now + 5)
check("within the TTL nothing is asked again (cached)", all("/now" not in u and "/feed" not in u for u in PCALLS), PCALLS)
PCALLS.clear(); C.do_visit_pino_api(L, st, now + 40)
check("now/feed asked again after their TTLs", any("/now" in u for u in PCALLS) and any("/feed" in u for u in PCALLS))
check("who is cached for 10 min", C.PINO_TTL["who"] == 600 and C.PINO_TTL["now"] == 15 and C.PINO_TTL["feed"] == 30 and C.PINO_TTL["mind"] == 60 and C.PINO_TTL["memories"] == 300)
os.remove(C.PINO_CACHE); PINO["code"] = 503
check("503 -> he is away, handled", C.do_visit_pino_api(L, C.new_state(), now + 100) == "ok (pino away)")
PINO["code"] = 200
st = C.new_state()
v = C.validate(L, st, P, {"action": "look_up", "params": {"topic": "what Pino is doing"}}, now)
check("a Pino web search on a tick goes to his API instead", v[0] == "none" and "visit_pino" in v[2], v)
v = C.validate(L, st, dict(P, talk=True), {"action": "look_up", "params": {"topic": "Pino the kiwi"}}, now)
check("Zack asking in chat still gets the search", v[2] == "ok", v)
st["recent"] = [[now - 600, "visit_pino"]]
check("visit_pino cooldown: 30 min", C.blocked(L, st, P, "visit_pino", now) and not C.blocked(L, st, P, "visit_pino", now + 1300))
r = C.do_pino_post(L, st, {"text": "Hello from Night City"}, now)
rows = [json.loads(l) for l in open(C.PINO_POSTS)]
check("posting is off: nothing sent, exactly what would be left is logged", rows[-1]["status"].startswith("not sent") and rows[-1]["text"] == "Hello from Night City - Cypher (an AI on Zack's cyberdeck)", rows)
check("visit_pinos_world is not offered while posting is off", "visit_pinos_world" not in C.manifest_acts(L, C.new_state(), P, now))

# ================= 7. the lore codex =================
reset_mind()
C.searxng_bases = lambda K: ["http://searx"]
C.searxng_search = lambda K, q: [{"url": "https://cyberpunk.fandom.com/wiki/Arasaka", "snippet": "Arasaka is a Japanese megacorporation in security and banking."},
                                 {"url": "https://example.org/a", "snippet": "Founded by Saburo Arasaka."}]
C.read_page = lambda K, u, snippet="": "Arasaka Corporation is a world-wide megacorp dealing in corporate security, banking and manufacturing."
st = C.new_state()
check("research_lore offered with an empty draft", "research_lore" in C.manifest_acts(L, st, P, now) and "write_codex" not in C.manifest_acts(L, st, P, now))
r = C.execute("research_lore", {}, L, st, P)
d = C.load_lore()
check("facts gathered for the next queued topic, with sources", r == "ok" and d["draft"]["topic"] == "Arasaka" and {"cyberpunk.fandom.com", "example.org"} <= {f["source"] for f in d["draft"]["facts"]}, d["draft"])
check("a work loop opened for it", any(x["text"] == "codex entry: Arasaka" for x in st["loops"]))
check("no second research until it is written", C.blocked(L, st, P, "research_lore", now) and "write_codex" in C.manifest_acts(L, st, P, now))
v = C.validate(L, st, P, {"action": "write_codex", "params": {"text": "Arasaka runs security and banks and half of Night City's fear.",
                                                                "take": "I think their tower is a gravestone.", "queue": ["Kang Tao"]}}, now)
check("write_codex validates", v[2] == "ok", v)
b0 = st["drives"]["boredom"]
r = C.execute("write_codex", v[1], L, st, P)
cx = C.load_codex()
check("the entry is saved, his take and the facts kept apart", r.startswith("ok (codex d0001)") and cx[-1]["his_take"] == "I think their tower is a gravestone."
      and cx[-1]["facts"] and "Arasaka runs" in cx[-1]["entry"], cx)
check("it counts as something he made", any(m["ref"] == "d0001" for m in C.read_json(C.MADE_FILE, [])))
check("the loop closed itself", not any(x["text"] == "codex entry: Arasaka" for x in st["loops"]))
check("the queue does not repeat a topic, and his addition is queued", C.lore_next(C.load_lore())["topic"] != "Arasaka" and any(q["topic"] == "Kang Tao" for q in C.load_lore()["queue"]))
check("finishing an entry is a drive reward", C.ACTION_EFFECTS["write_codex"]["boredom"] <= -0.15)
v = C.validate(L, st, P, {"action": "research_lore", "params": {"topic": "Arasaka (corps)"}}, now)
check("a written topic (even with its category copied) goes on to the next queued one", v[2] == "ok" and v[1] == {}, v)
check("category tails are stripped", C.lore_topic_clean("Tyger Claws [gangs]") == "Tyger Claws" and C.lore_topic_clean("Arasaka (corps)") == "Arasaka")
check("lore entries may talk about security and locks (fiction)", C.validate(L, dict(st), P, {"action": "write_codex", "params": {
      "text": "Militech sells security, locks down whole districts and arms the NCPD with surplus war tech."}}, now)[2] in ("ok", "rejected: no facts gathered yet (research_lore first)"))
_ss, _rp = C.searxng_search, C.read_page
C.searxng_search = lambda K, q: [{"url": "https://www.cyberpunk.net/", "snippet": "Immerse yourself in the Cyberpunk universe."},
                                 {"url": "https://cyberpunk.fandom.com/wiki/X", "snippet": q.replace("Cyberpunk ", "").replace(" lore", "") + " is a megacorp out of Night City."}]
C.read_page = lambda K, u, snippet="": None
C.execute("research_lore", {}, L, st, P)
ll = C.lore_lines(L, st, now)
check("site blurbs that never name the topic are dropped from the facts", "Immerse yourself" not in ll, ll)
check("with a draft pending, the prompt carries the facts to write from", "write the" in ll and "megacorp" in ll.lower() and "[" in ll, ll)
check("an entry tick may answer longer (no cut JSON)", C.CODEX_TOKENS >= 300)
check("a 'Cyberpunk 2077:' prefix is stripped from topics", C.lore_topic_clean("Cyberpunk 2077: Militech corporate structure") == "Militech corporate structure")
check("lore_about: an entry must name its topic", C.lore_about("Maelstrom: a chrome-mad gang", "Maelstrom") and not C.lore_about("The grid hums like a tired god.", "Biotechnica"))
v = C.validate(L, st, P, {"action": "write_codex", "params": {"text": "The grid hums like a tired god. Data flows in streams, never still. I watch it."}}, now)
check("a codex entry that drifts off its topic is refused with the topic named", v[2].startswith("rejected: the entry is about"), v)
stp = {"recent_keys": []}
for i, k in enumerate(["research_lore", "write_codex", "rest", "go_to:noodle_stall"] * 3):
    stp["recent_keys"].append([now - 3600 + i * 300, k])
pp = C.predictability(stp, now)
check("a 4-step round is seen as predictable", pp and pp["score"] >= C.PREDICTABLE_AT and pp["period"] == 4 and "noodle stall" in pp["round"], pp)
C.searxng_search, C.read_page = _ss, _rp
check("and the prompt names the round", "same round" in C.habit_lines(L, stp, ["go_to"], now))
check("lore searches of Pino are refused", C.validate(L, st, P, {"action": "research_lore", "params": {"topic": "Pino lore"}}, now)[0] == "none")

# ================= 8. the slim prompt =================
reset_mind()
st = C.new_state(); st["mood"] = C.mood(st["drives"])
Lfat = json.loads(json.dumps(L)); Lfat["features"] = {"slim_prompt": False}
slim = sum(len(m["content"]) for m in C.build_messages(L, st, P, now))
fat = sum(len(m["content"]) for m in C.build_messages(Lfat, st, P, now))
check("slim prompt is smaller than the old one", slim < fat, (slim, fat))
m = C.build_messages(L, st, P, now)
check("slim prompt keeps the rules that matter", all(w in m[0]["content"] for w in ("trust the NOW line", "never approve, unlock or authorize", "Instagram", "never tells you what to do")))
check("slim prompt has the loops sidecar", '"loop"' in m[0]["content"] and "your open loops" in m[1]["content"])
check("and asks for fresh reasons", "fresh words" in m[0]["content"])
print("prompt chars: slim %d, old %d" % (slim, fat))

# ================= 9. a day of ticks breaks the loop =================
reset_mind()
st = C.new_state(); PX["queue"].clear()
seq = []
def brain_pace():
    # a brain stuck pacing: apartment, noodle stall, apartment...
    pl = "noodle_stall" if (st.get("place") or "apartment") == "apartment" else "apartment"
    return J({"action": "go_to", "params": {"place": pl}, "reason": "a quiet evening walk", "thread": {"open": "watch Pino's feed later"}})
t = now
for i in range(30):
    PX["reply"] = brain_pace()
    e = C.tick(L, st, t, perceive_fn=perceive(dict(P, focused_app="foot%d" % i)), camera_fn=lambda L, s, n: [], inbox_fn=lambda L, s, n: [], talk_fn=lambda *a: 0)
    if e: seq.append(e)
    t += 300
check("no 'thread refused' in a day of ticks", not any("thread refused" in json.dumps(e) for e in seq))
check("every decision saves its prompt size and context", all("prompt_chars" in e and "ctx" in e for e in seq if e.get("choice")), seq[-1])
last_prompt = PX["seen"][-1]["messages"][1]["content"]
check("the pacing shows up as predictable in the prompt", "predictable" in last_prompt, last_prompt[:800])
check("boredom rises while he paces (the fear)", st["drives"]["boredom"] > 0.5, st["drives"])

# ================= 10. interviews =================
PX["reply"] = J({"answer": "I kept walking because the street felt safe. The quiet-evening reason was stale; I reused it."})
rec = C.interview(L, st, "Why did you pace between the apartment and the noodle stall?", C.interview_entries(L, time.strftime("%Y-%m-%d", time.localtime(now))), now=t)
check("interview answered by Alpha's brain", rec.get("brain") == "alpha" and "stale" in rec["answer"], rec)
check("both sides saved", json.loads(open(C.INTERVIEWS_FILE).read().splitlines()[-1])["question"].startswith("Why did you pace"))
check("the interview prompt carries the decisions", "go_to" in PX["seen"][-1]["messages"][1]["content"] and rec["prompt_chars"] < 6000, rec)
check("it never counts as a message to Zack", not any(x == "message_zack" for _, x in st.get("recent") or []))

# ================= 11. migration =================
reset_mind()
os.makedirs(os.path.dirname(C.MEM_FILE), exist_ok=True)
json.dump([{"day": "2026-11-1%d" % i, "text": "quiet night %d at the apartment" % i} for i in range(8)], open(C.MEM_FILE, "w"))
st = C.new_state()
st["threads"] = [{"id": 3, "text": "watch Pino's feed later", "since": now - 5 * 86400, "touched": now - 3 * 86400},
                 {"id": 7, "text": "find the noodle cook's name", "since": now - 600, "touched": now - 600}]
st["thread_seq"] = 7
r = C.migrate15(L, st, now)
check("migration: memories to the library and working memory", r["memories"] == 8 and len(C.load_wm()) == 6, r)
check("stale threads let go, fresh ones become loops", r["threads_shelved"] == 1 and r["loops"] == 1 and st["threads"] == [] and st["loops"][0]["id"] == 7, r)
check("lessons became rule beliefs", r["lessons"] >= 1 and any(b["kind"] == "rule" for b in C.load_beliefs()))
check("migration runs once", C.migrate15(L, st, now) is None)
o = C.open_loop(st, "a new thing to chase", "want", now)
check("new loop ids continue after the old threads", o["id"] == 8, o)

# ================= 12. hand-off carries the new state =================
st["place"] = "library"; C.note_key(st, "library", {}, now)
s = C.export_state(L, st)
check("export carries place, loops, habits and the mind", s.get("place") == "library" and s.get("loops") and s.get("recent_keys") and isinstance(s.get("mind"), dict) and s["mind"].get("wm"))
check("exported state fits the proxy (512 KB)", len(json.dumps(s)) < 512 * 1024, len(json.dumps(s)))
st2 = A.new_state(); A.adopt_state(st2, json.loads(json.dumps(s)))
check("the other host adopts place, loops and habits", st2["place"] == "library" and st2["loops"] and st2["recent_keys"], {k: st2.get(k) for k in ("place", "loops")})
check("...and the mind (working memory, beliefs)", len(A.load_wm()) == 6 and A.load_beliefs(), (len(A.load_wm()), len(A.load_beliefs())))

# ================= 13. full text in the journal and the chat view =================
import importlib
sys.path.insert(0, SRC); CJ = importlib.import_module("cypher_journal")
long = "word " * 300
v = CJ.view({"ts": "2026-11-16T14:00:00-0500", "event": "talk", "user": "tell me everything", "reply": long})
check("conversation replies are shown whole (was 600)", len(v["result"]) > 1400, len(v["result"]))
jd = os.path.join(T, "jtest", "journal"); os.makedirs(jd, exist_ok=True)
with open(os.path.join(jd, "2026-11-16.jsonl"), "w") as fh:
    fh.write(J({"ts": "2026-11-16T14:00:00-0500", "event": "talk", "user": "hi", "reply": "hey"}) + "\n")
    fh.write(J({"ts": "2026-11-16T14:01:00-0500", "choice": {"action": "rest", "params": {}}, "validator": "ok", "reason": "tired"}) + "\n")
    fh.write(J({"ts": "2026-11-16T14:02:00-0500", "event": "interview", "asker": "Zack", "question": "why?", "answer": "because"}) + "\n")
rows = CJ.entries(data_dir=os.path.join(T, "jtest"), kinds=CJ.CHAT_KINDS)
check("chat view: only conversations and interviews", [r["kind"] for r in rows] == ["interview", "talk"], rows)
check("chat text has no 'result:' prefix", "result:" not in CJ.text(rows[1]))
nn = open(os.path.join(NOVA, "nova_native.py")).read()
check("HUD: long replies scroll, Super+H opens the chat", "set_max_content_height" in nn and '("h", "H")' in nn and "CHAT_KINDS" in nn)
check("chat turns are recorded whole", "scrub(prompt, 4000)" in open(os.path.join(NOVA, "cypher_link.py")).read())
cli = open(os.path.join(SRC, "grokbot-cypher")).read()
check("grokbot-cypher has chat, interview, codex, library, features", all(w in cli for w in ('cmd == "chat"', '"interview"', '"codex"', '"library"', '"features"')))

# ================= 14. README credits Pino =================
rd = open(os.path.join(ROOT, "README.md")).read()
check("README credits Pino as inspiration", "pinos.world" in rd and "Pino" in rd)

srv.shutdown()
print("%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
