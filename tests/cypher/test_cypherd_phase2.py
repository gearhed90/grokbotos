#!/usr/bin/env python3
"""Phase 2 tests for cypherd: camera feed, local fallback brain, nightly sleep with
versioned preferences, and the failover lease/sync client on both hosts (deck and
Alpha standby). Fake proxy and brains on localhost; no display, root or network."""
import importlib.util, json, os, socket, sys, tempfile, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "cypher")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

# ---- fake Alpha proxy + fake local model ----
PX = {"lease": {"granted": True, "epoch": 1, "why": "primary", "holder": "cypher"}, "status": None, "calls": [],
      "chat_code": 503, "chat_busy": "gaming", "events": [], "last_seq": 0, "saved": {}, "journal": [], "pushed": []}
LOCAL = {"up": True, "reply": '{"action":"journal_thought","params":{"text":"Porch light of the grid."},"reason":"camera"}', "seen": []}
class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, o):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); q = dict(urllib.parse.parse_qsl(u.query))
        PX["calls"].append(("GET", u.path, q, self.headers.get("Authorization")))
        if u.path == "/camera/events":
            since = int(q.get("since", 0))
            return self._j(200, {"events": [e for e in PX["events"] if e.get("seq", 0) > since], "last_seq": PX["last_seq"]})
        if u.path == "/sync/state": return self._j(200, {"saved": PX["saved"]})
        if u.path == "/sync/journal": return self._j(200, {"entries": [e for e in PX["journal"] if e["ts"] > q.get("since", "")]})
        self._j(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        PX["calls"].append(("POST", self.path, body, self.headers.get("Authorization")))
        if self.path == "/lease":
            if body.get("op") == "status" and PX["status"] is not None: return self._j(200, PX["status"])
            r = PX["lease"]; return self._j(200, r(body) if callable(r) else r)
        if self.path == "/sync/state": PX["pushed"].append(body); return self._j(200, {"saved": True})
        if self.path == "/sync/journal": PX["pushed"].append(body); return self._j(200, {"added": len(body["entries"])})
        if PX["chat_code"] != 200: return self._j(PX["chat_code"], {"busy": PX["chat_busy"]})
        self._j(200, {"model": "fake-alpha", "choices": [{"message": {"content": '{"action":"none","reason":"alpha"}'}}]})
class Local(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); LOCAL["seen"].append(body)
        b = json.dumps({"choices": [{"message": {"content": LOCAL["reply"]}}], "usage": {"prompt_tokens": 500, "completion_tokens": 30}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
ports = {"px": free_port(), "local": free_port()}
for k, H in (("px", Proxy), ("local", Local)):
    srv = ThreadingHTTPServer(("127.0.0.1", ports[k]), H); threading.Thread(target=srv.serve_forever, daemon=True).start()

T = tempfile.mkdtemp(); TOKEN = "k" * 40
with open(os.path.join(T, "token"), "w") as f: f.write(TOKEN)
os.chmod(os.path.join(T, "token"), 0o600)
limits_src = json.load(open(os.path.join(SRC, "cypher-limits.json")))
def write_limits(name="limits.json", **over):
    L = json.loads(json.dumps(limits_src))
    L["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % ports["px"]]; L["brain"]["primary_url"] = L["brain"]["primary_urls"][0]
    L["brain"]["local"]["url"] = "http://127.0.0.1:%d" % ports["local"]; L["brain"]["local"]["timeout_s"] = 5
    L["brain"]["hosted_backup"]["enabled"] = False
    L["failover"]["deck_addrs"] = ["127.0.0.1:%d" % free_port()]           # nothing listens: deck dark
    L.update(over)
    p = os.path.join(T, name)
    with open(p, "w") as f: json.dump(L, f)
    return p

def load(host, tag):
    env = dict(CYPHER_LIMITS=write_limits(tag + "-limits.json"), CYPHER_LIMITS_INSECURE_OK="1", CYPHER_HOST=host,
               CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"), CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"),
               CYPHER_CONFIG_DIR=os.path.join(T, tag, "cfg"), CYPHER_STATE_DIR=os.path.join(T, tag, "state"),
               CYPHER_DATA_DIR=os.path.join(T, tag, "data"), CYPHER_PERSONA=os.path.join(SRC, "persona.md"),
               CYPHER_DRY_RUN="1", TZ="America/New_York")
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location("cypherd_" + tag, os.path.join(SRC, "cypherd.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

D = load("deck", "deck")
L = D.current_limits(D.new_state())

# ---- shipped phase-2 limits ----
S = D.load_limits(os.path.join(SRC, "cypher-limits.json"))
check("phase 2 unlocked", S["phase_max"] == 2)
check("failover, camera, sleep, local all on", all(D.phase_on(S, b) for b in ("failover", "camera", "sleep", "local")))
check("local model is loopback only", S["brain"]["local"]["url"].startswith("http://127.0.0.1:"))
check("deck addresses: LAN and tailnet", S["failover"]["deck_addrs"] == ["192.168.12.71:22", "100.72.32.17:22"])
check("proxy reachable on LAN then tailnet", S["brain"]["primary_urls"] == ["http://192.168.12.126:8090", "http://100.114.239.111:8090"])
check("no action can be a camera/house control", not any(D.HOUSE_WORDS.search(a) for a in S["actions"]))
bad = json.loads(json.dumps(limits_src)); bad["actions"]["camera_ptz"] = {"phase": 1}
try: D.validate_limits(bad); check("limits with a camera action refused", False)
except D.ConfigError: check("limits with a camera action refused", True)
bad = json.loads(json.dumps(limits_src)); bad["actions"]["lights_off"] = {"phase": 1}
try: D.validate_limits(bad); check("limits with a lights action refused", False)
except D.ConfigError: check("limits with a lights action refused", True)

# ---- camera feed ----
now = time.time()
def ev(seq, kind, ago, **kw):
    return dict({"seq": seq, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - ago)), "camera": "front_door",
                 "kind": kind, "alerted": None, "source": "review", "id": "front_door-20261115-000000"}, **kw)
PX["events"] = [ev(1, "family", 7 * 3600, names=["Zack"]), ev(2, "motion_dropped", 600), ev(3, "stranger", 300, alerted=True),
                ev(4, "person", 60, names=["Zack", "rm -rf"], description="olive tee", folder="/home/x")]
PX["last_seq"] = 4
st = D.new_state()
evs = D.camera_step(L, st, now)
check("first fetch looks back 12 h, boring kinds skipped", [e["seq"] for e in evs] == [1, 3, 4], evs)
check("unknown fields dropped, names must be first names", "description" not in evs[2] and "folder" not in evs[2] and evs[2]["names"] == ["Zack"], evs[2])
check("cursor advanced", st["cam_seq"] == 4)
check("camera call carries the token", PX["calls"][-1][3] == "Bearer " + TOKEN)
PX["events"].append(ev(5, "person", 4000)); PX["last_seq"] = 5
check("later fetches: only the last 30 min", D.camera_step(L, st, now) == [] and st["cam_seq"] == 5)
PX["last_seq"] = 2; D.camera_step(L, st, now); check("feed reset follows the feed", st["cam_seq"] == 2)
check("camera off below phase 2", D.camera_step(dict(L, phase_max=1), D.new_state(), now) == [])
line = D.camera_line(evs); check("prompt line: time, camera, kind, names, alerted", "family (Zack)" in line and "Zack was alerted" in line, line)

P = {"presence": "active", "dnd": False, "muted": False, "quiet_hours": False, "camera": evs}
st2 = D.new_state()
check("camera tick: note refused", D.validate(L, st2, P, {"action": "show_note", "params": {"text": "Someone at the door"}})[2].startswith("rejected: camera events"))
check("camera tick: avatar refused", D.validate(L, st2, P, {"action": "set_avatar_color", "params": {"color": "red"}})[2].startswith("rejected: camera events"))
check("camera tick: journal ok", D.validate(L, st2, P, {"action": "journal_thought", "params": {"text": "Zack is home."}})[2] == "ok")
for a in ("turn_on_lights", "camera_snapshot", "unlock_door", "ptz_move", "start_recording"):
    v = D.validate(L, st2, dict(P, camera=[]), {"action": a, "params": {}})[2]
    check("house action %s never allowed" % a, v == "rejected: camera and house controls are never available", v)

# tick with camera events: nudges, journal, prompt
fakep = lambda L, now: {"local_time": "Sun 2:00 PM", "hour": 14, "quiet_hours": False, "presence": "active",
                        "focused_app": "", "window_title": "", "dnd": False, "muted": False}
st3 = D.new_state(); st3["last_tick"] = now; before = dict(st3["drives"])
PX["chat_code"] = 503; LOCAL["seen"].clear()
e = D.tick(L, st3, now, perceive_fn=fakep, camera_fn=lambda L, st, n: [ev(9, "stranger", 30, alerted=True)])
check("stranger raises curiosity and focus", st3["drives"]["curiosity"] > before["curiosity"] and st3["drives"]["focus"] > before["focus"], st3["drives"])
check("journal entry carries the camera events", e["perception"]["camera"][0]["kind"] == "stranger", e)
check("prompt tells the model the feed is read-only", "read-only feed" in LOCAL["seen"][-1]["messages"][1]["content"])

# ---- local fallback ----
check("Alpha in gaming mode -> local model answered", e["brain"] == "local" and "alpha_gaming" in e["brain_notes"], e)
check("local reply journaled", e["choice"]["action"] == "journal_thought" and e["validator"] == "ok", e)
check("local request asks for JSON", LOCAL["seen"][-1].get("response_format") == {"type": "json_object"})
PX["chat_code"] = 200
c = D.think(L, D.new_state(), [{"role": "user", "content": "x"}], now)
check("Alpha free -> Alpha first", c[1] == "alpha", c)
PX["chat_code"] = 503; Ldown = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"}))
Ldown["brain"]["local"]["url"] = "http://127.0.0.1:%d" % free_port(); Ldown = D.validate_limits(Ldown)
st4 = D.new_state()
try: D.think(Ldown, st4, [{"role": "user", "content": "x"}], now); check("local down, hosted off -> busy", False)
except D.BrainBusy as b: check("local down, hosted off -> busy", "local_unreachable" in b.reason and "backup_off" in b.reason, b.reason)
check("local down -> backs off", st4["local_backoff_until"] > now)
Loff = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"})); Loff["brain"]["local"]["enabled"] = False
try: D.think(D.validate_limits(Loff), D.new_state(), [{"role": "user", "content": "x"}], now); check("local off skipped", False)
except D.BrainBusy as b: check("local off skipped", "local" not in b.reason, b.reason)

# ---- nightly sleep ----
day = "2026-11-14"
D._private_dir(os.path.join(D.DATA_DIR, "journal"))
with open(os.path.join(D.DATA_DIR, "journal", day + ".jsonl"), "w") as f:
    for i in range(6):
        f.write(json.dumps({"ts": "%sT2%d:00:00-0500" % (day, i), "tick": i, "mood": "content", "brain": "alpha",
                            "choice": {"action": "journal_thought", "params": {"text": "thought %d" % i}}, "reason": "r",
                            "perception": {"camera": [{"kind": "family"}] if i == 2 else []}}) + "\n")
st5 = D.new_state()
LOCAL["reply"] = json.dumps({"memories": ["Zack came home at 8 PM; the porch was calm.", "http://evil.example/x", "x" * 400],
                             "add_notes": ["Quiet evenings: journal, do not ping.", "Zack likes short notes.", "third"],
                             "drop_notes": [7], "drift_adjust": {"boredom": -0.5, "curiosity": 0.01, "bogus": 1}, "reason": "calm day"})
at4 = time.mktime((2026, 11, 15, 4, 5, 0, 0, 0, -1))
s1 = D.maybe_sleep(L, st5, at4)
check("sleep runs after 4 AM for yesterday", s1 and s1["day"] == day and s1["event"] == "sleep", s1)
check("sleep used a brain", s1["brain"] == "local", s1)
check("URL memory refused, long one cut", len(s1["memories_added"]) == 2 and all(len(m) <= 140 for m in s1["memories_added"]), s1)
check("at most 2 notes added", s1["pref_changes"]["added"] == ["Quiet evenings: journal, do not ping.", "Zack likes short notes."], s1)
check("drift step clamped to 0.02", s1["pref_changes"]["drift"]["boredom"][1] == round(D.DEFAULT_DRIFT["boredom"] - 0.02, 4), s1)
check("unknown drive ignored", "bogus" not in s1["pref_changes"]["drift"])
check("prefs version 1 saved", D.read_json(D.PREFS_FILE)["version"] == 1 and os.path.exists(os.path.join(D.PREFS_DIR, "v0001.json")))
check("tunables follow, still clamped on load", D.load_tunables(L)["drift_per_hour"]["boredom"] == round(D.DEFAULT_DRIFT["boredom"] - 0.02, 4))
check("stats count camera and ticks", s1["stats"]["ticks"] == 6 and s1["stats"]["camera"] == {"family": 1}, s1["stats"])
check("sleep only once a day", D.maybe_sleep(L, st5, at4 + 600) is None)
check("no sleep before 4 AM", D.maybe_sleep(L, D.new_state(), time.mktime((2026, 11, 15, 3, 59, 0, 0, 0, -1))) is None)
check("memories reach the prompt", "Zack came home" in D.memory_lines() and "Quiet evenings" in D.memory_lines())
LOCAL["reply"] = json.dumps({"memories": [], "add_notes": ["Another note"], "drop_notes": [0]})
s2 = D.maybe_sleep(L, D.new_state(), time.mktime((2026, 11, 16, 4, 1, 0, 0, 0, -1)))
check("second night: version 2, note dropped and added", D.read_json(D.PREFS_FILE)["version"] == 2 and
      D.read_json(D.PREFS_FILE)["notes"] == ["Zack likes short notes.", "Another note"], D.read_json(D.PREFS_FILE))
check("no memories from the model -> a stats memory", s2["memories_added"][0].startswith("2026-11-15:"), s2)
v = D.prefs_rollback(1)
check("rollback to v1 makes v3", v == 3 and D.read_json(D.PREFS_FILE)["notes"] == ["Quiet evenings: journal, do not ping.", "Zack likes short notes."])
check("rollback recorded", D.read_json(os.path.join(D.PREFS_DIR, "v0003.json"))["changes"] == {"rollback_to": 1})
try: D.prefs_rollback(99); check("missing version refused", False)
except D.ConfigError: check("missing version refused", True)
D.cli(["sleep-now"]); check("sleep-now flag", D.sleep_now_requested())
s3 = D.maybe_sleep(L, D.new_state(), time.mktime((2026, 11, 16, 15, 0, 0, 0, 0, -1)))
check("sleep-now condenses today, any hour, and clears the flag", s3 and s3["day"] == "2026-11-16" and not D.sleep_now_requested(), s3)
mem = D.read_json(D.MEM_FILE)
check("memories capped", len(mem) <= 60)
for i in range(40):
    D.apply_sleep(L, "2026-12-%02d" % (i % 28 + 1), {"add_notes": ["n%d" % i], "drop_notes": [0]}, D.day_stats([]), "test")
check("pref notes capped at 8", len(D.read_json(D.PREFS_FILE)["notes"]) <= 8)
check("only the last 30 versions kept", len(os.listdir(D.PREFS_DIR)) == 30, len(os.listdir(D.PREFS_DIR)))
check("pref files private", all(os.stat(os.path.join(D.PREFS_DIR, f)).st_mode & 0o077 == 0 for f in os.listdir(D.PREFS_DIR)))

# ---- failover, deck side ----
PX["calls"].clear(); PX["lease"] = {"granted": True, "epoch": 7, "why": "preempted_alpha", "holder": "cypher"}
PX["saved"] = {"holder": "alpha", "epoch": 6, "state": {"drives": {"energy": 0.11, "curiosity": 0.9, "social": 0.2, "boredom": 0.3, "focus": 0.4},
               "last_actions": ["journal_thought"], "cam_seq": 40, "tick": 500, "limits": {"evil": 1}}}
PX["journal"] = [{"ts": "2026-11-15T03:10:00-0500", "tick": 498, "host": "alpha", "id": "alpha:6:498:x", "choice": {"action": "none"}},
                 {"ts": "2026-11-15T03:11:00-0500", "tick": 499, "host": "alpha", "id": "alpha:6:499:y", "choice": {"action": "none"}}]
std = D.new_state(); std["lease_epoch"] = 5
check("deck always thinks", D.mind_step(L, std) is True)
check("deck adopted Alpha's mind on hand-back", std["drives"]["energy"] == 0.11 and std["cam_seq"] == 40 and std["tick"] == 500, std)
check("deck ignores limits from the store", "deck_limits" not in std or std["deck_limits"] is None)
jl = open(os.path.join(D.DATA_DIR, "journal", "2026-11-15.jsonl")).read()
check("Alpha's entries merged into the deck journal", "alpha:6:498:x" in jl and "alpha:6:499:y" in jl)
check("hand-back journaled", '"event": "handback"' in jl)
check("merge cursor saved", std["merged_since"] == "2026-11-15T03:11:00-0500")
check("lease acquire sent with the old epoch", [c for c in PX["calls"] if c[1] == "/lease"][0][2] == {"holder": "cypher", "op": "acquire", "epoch": 5})
PX["calls"].clear(); D.mind_step(L, std)
check("same epoch -> no second catch-up", not any(c[1] == "/sync/state" for c in PX["calls"]))
PX["pushed"].clear(); D._OUTBOX[:] = [{"ts": "2026-11-15T03:20:00-0500", "tick": 501}]
D.sync_push(L, std)
sp = [b for b in PX["pushed"] if "state" in b]
check("deck pushes its state with epoch and its limits", sp and sp[0]["epoch"] == 7 and sp[0]["holder"] == "cypher" and sp[0]["state"]["limits"]["phase_max"] == 2, sp)
check("deck pushes its journal outbox, then clears it", any("entries" in b for b in PX["pushed"]) and D._OUTBOX == [])
PX["calls"].clear(); D.release(L, std, handoff=False)
rl = [c[2] for c in PX["calls"] if c[1] == "/lease"]
check("kill switch releases without hand-off (parked)", rl and rl[-1]["op"] == "release" and rl[-1]["handoff"] is False, rl)
dead = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"})); dead["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % free_port()]
std2 = D.new_state(); now2 = time.time()
check("proxy unreachable: deck still thinks", D.mind_step(D.validate_limits(dead), std2) is True)
check("...and stops asking Alpha for a while", std2["alpha_backoff_until"] > now2)

# ---- failover, Alpha standby side ----
A = load("alpha", "alpha")
LA = A.current_limits(A.new_state())
check("Alpha: notes and avatar locked, no hosted, no local", "show_note" not in A.allowed_actions(LA) and
      "set_avatar_color" not in A.allowed_actions(LA) and not LA["brain"]["hosted_backup"]["enabled"] and not A.phase_on(LA, "local"))
check("Alpha perception: deck offline", A.perceive_alpha(LA)["presence"] == "deck_offline")
sta = A.new_state()
PX["status"] = {"holder": "cypher", "epoch": 7, "released": False, "expires": time.time() + 100, "parked": False, "now": time.time()}
check("deck holds a live lease -> stand by", A.mind_step(LA, sta) is False and not sta["holding"])
PX["status"] = dict(PX["status"], released=True, parked=True)
check("parked lease -> stand by", A.mind_step(LA, sta) is False)
deck = socket.socket(); deck.bind(("127.0.0.1", 0)); deck.listen(5)
LAx = json.loads(json.dumps({k: v for k, v in LA.items() if k != "_quiet_nights"})); LAx["failover"]["deck_addrs"] = ["127.0.0.1:%d" % deck.getsockname()[1]]
LAx = A.validate_limits(LAx)
PX["status"] = {"holder": "cypher", "epoch": 7, "released": False, "expires": time.time() - 5, "parked": False, "now": time.time()}
PX["calls"].clear()
check("expired but the deck answers -> no takeover", A.mind_step(LAx, sta) is False and not any(c[2].get("op") == "acquire" for c in PX["calls"] if c[1] == "/lease"))
deck.close()
PX["lease"] = lambda b: {"granted": True, "epoch": 8, "why": "takeover", "holder": "alpha"} if b["op"] == "acquire" else {"granted": True, "epoch": 8, "why": "renewed"}
PX["saved"] = {"holder": "cypher", "epoch": 7, "state": {"drives": {"energy": 0.66, "curiosity": 0.5, "social": 0.5, "boredom": 0.5, "focus": 0.5},
               "cam_seq": 77, "limits": dict(json.loads(json.dumps(limits_src)), tick_s=60), "prefs": {"version": 50, "notes": ["synced note"]}}}
PX["calls"].clear()
check("expired + deck dark -> takeover", A.mind_step(LA, sta) is True and sta["holding"] and sta["lease_epoch"] == 8)
acq = [c[2] for c in PX["calls"] if c[1] == "/lease" and c[2]["op"] == "acquire"][0]
check("takeover asserts the deck is unreachable", acq["deck_unreachable"] is True and acq["holder"] == "alpha", acq)
check("Alpha adopted the deck's mind", sta["drives"]["energy"] == 0.66 and sta["cam_seq"] == 77)
check("Alpha uses the deck's synced limits (with its own overrides)", A.current_limits(sta)["tick_s"] == 60 and "show_note" not in A.allowed_actions(A.current_limits(sta)))
check("synced prefs adopted when newer", A.read_json(A.PREFS_FILE)["notes"] == ["synced note"])
check("takeover journaled on Alpha", '"event": "takeover"' in open(os.path.join(A.DATA_DIR, "journal", time.strftime("%Y-%m-%d") + ".jsonl")).read())
check("holding -> renew each tick", A.mind_step(LA, sta) is True)
PX["status"] = None
PX["pushed"].clear(); A.sync_push(LA, sta)
sp = [b for b in PX["pushed"] if "state" in b]
check("Alpha pushes state without limits", sp and "limits" not in sp[0]["state"] and sp[0]["holder"] == "alpha", sp)
PX["lease"] = {"granted": False, "epoch": 9, "why": "lost", "holder": "cypher"}
check("deck back -> renew refused -> Alpha stands down", A.mind_step(LA, sta) is False and not sta["holding"])
check("hand-back journaled on Alpha", '"event": "handed_back"' in open(os.path.join(A.DATA_DIR, "journal", time.strftime("%Y-%m-%d") + ".jsonl")).read())
PX["status"] = {"holder": None, "epoch": 9, "released": True, "expires": 0, "parked": False, "now": time.time()}
PX["lease"] = lambda b: {"granted": True, "epoch": 10, "why": "takeover", "holder": "alpha"}
PX["calls"].clear()
check("clean release -> takeover without probing", A.mind_step(LA, A.new_state()) is True and
      [c[2] for c in PX["calls"] if c[1] == "/lease" and c[2]["op"] == "acquire"][0]["deck_unreachable"] is False)
e = A.tick(LA, A.new_state(), time.time(), camera_fn=lambda L, st, n: [])
check("Alpha tick journals with host alpha", e is None or e.get("host") == "alpha", e)
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
