#!/usr/bin/env python3
"""Phase 5 tests (build 11): quiet hours spelled out to every brain (weekday nights only),
stricter request_account (plain domain + known TLD, Alpha or hosted brain only), message_zack
defaults (3 an hour, no daily cap), the limits command (bounds, 'none', live reload), gridwatch
(check_grid + HUD report, nothing secret), and self-tuning proposals that apply only with
`tuning approve` (never from a phone reply, the screen, or the local 3B). Fake proxy, fake
local model, fake GitHub and ntfy; no display, root or network."""
import contextlib, importlib.util, io, json, os, socket, stat, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "build_files", "rpi5", "cypher")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:400]))
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

PX = {"reply": '{"action":"none","params":{},"reason":"x"}', "seen": [], "up": True,
      "lease": {"holder": "cypher", "epoch": 3, "expires": time.time() + 3600, "released": False},
      "alpha_journal": [{"ts": "2026-11-16T10:09:00-0500", "tick": 9}]}
LX = {"reply": '{"action":"none","params":{},"reason":"x"}', "seen": []}
class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/health"): return self._j(200, {"ok": True, "busy": None})
        if self.path.startswith("/sync/state"): return self._j(200, {"lease": dict(PX["lease"]), "saved": {}})
        if self.path.startswith("/sync/journal"): return self._j(200, {"entries": PX["alpha_journal"]})
        if self.path.startswith("/camera/events"): return self._j(200, {"events": [], "last_seq": 0})
        self._j(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        PX["seen"].append(body)
        self._j(200, {"model": "fake", "choices": [{"message": {"content": PX["reply"]}}], "usage": {}})
class Local(Proxy):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LX["seen"].append(body)
        self._j(200, {"choices": [{"message": {"content": LX["reply"]}}]})
port, lport = free_port(), free_port()
for P_, H_ in ((port, Proxy), (lport, Local)):
    srv = ThreadingHTTPServer(("127.0.0.1", P_), H_); threading.Thread(target=srv.serve_forever, daemon=True).start()

T = tempfile.mkdtemp(); TOKEN = "k" * 12 + "TokSecret0123456789"; TOPIC = "cypher-" + "T0p1cSecretXyz_abcdefgh"
for n, v in (("token", TOKEN), ("topic", TOPIC)):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
L0 = json.load(open(os.path.join(SRC, "cypher-limits.json")))
L0["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % port]; L0["brain"]["primary_url"] = L0["brain"]["primary_urls"][0]
L0["brain"]["local"]["url"] = "http://127.0.0.1:%d" % lport; L0["brain"]["hosted_backup"]["enabled"] = False
L0["failover"]["enabled"] = False; L0["camera"]["enabled"] = False; L0["sleep"]["enabled"] = True
LIM = os.path.join(T, "limits.json")
with open(LIM, "w") as f: json.dump(L0, f, indent=2)
os.chmod(LIM, 0o644)
os.environ.update(CYPHER_LIMITS=LIM, CYPHER_LIMITS_INSECURE_OK="1",
                  CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"), CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"),
                  CYPHER_NTFY_TOPIC_FILE=os.path.join(T, "topic"), CYPHER_CONFIG_DIR=os.path.join(T, "cfg"),
                  CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_DATA_DIR=os.path.join(T, "data"),
                  CYPHER_PERSONA=os.path.join(SRC, "persona.md"), CYPHER_DRY_RUN="1", TZ="America/New_York",
                  XDG_RUNTIME_DIR=os.path.join(T, "run"))
for d in ("run", "state", "cfg"): os.makedirs(os.path.join(T, d), exist_ok=True)
def load(tag, host="deck"):
    os.environ["CYPHER_HOST"] = host
    spec = importlib.util.spec_from_file_location("cypherd_" + tag, os.path.join(SRC, "cypherd.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
C = load("p5"); A = load("p5a", "alpha"); os.environ["CYPHER_HOST"] = "deck"
L = C.current_limits(C.new_state())
def at(h, m=0, day=16):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))     # Mon Nov 16 2026
now = at(14)
P = {"local_time": "Mon 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": [], "brain": "alpha"}
def journal_text():
    d = os.path.join(T, "data", "journal")
    return "".join(open(os.path.join(d, f)).read() for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""
NT = {"sent": [], "gh": None}
def fake_http(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    if "api.github.com" in url:
        NT["gh_url"] = url
        if NT["gh"] is None: return 503, b""
        return 200, json.dumps(NT["gh"]).encode()
    NT["sent"].append({"url": url, "data": data}); return 200, b"{}"
C._http = fake_http
perceive = lambda p: (lambda L, n: dict(p))
SECRETS = (TOPIC, TOKEN, "192.168.", "100.114", "http://", "https://", "s4j6vbnk")

# ---- quiet hours: weekday nights only, and every brain is told ----
check("schedule in words", C.quiet_desc(L) == "11 PM-6 AM on Mon, Tue, Wed, Thu, Sun nights; none on Fri, Sat nights", C.quiet_desc(L))
for label, t, want in (("Sat 2 PM", at(14, 0, 21), False), ("Sun 1 AM (Sat night)", at(1, 0, 22), False),
                       ("Sun 2 PM", at(14, 0, 22), False), ("Sat 0:30 AM (Fri night)", at(0, 30, 21), False),
                       ("Fri 11:30 PM", at(23, 30, 20), False), ("Mon 1 AM (Sun night)", at(1, 0, 23), True),
                       ("Thu 11:30 PM", at(23, 30, 19), True), ("Tue 6:30 AM", at(6, 30, 17), False)):
    check("quiet hours %s -> %s" % (label, want), C.in_quiet_hours(L, t) is want)
st = C.new_state()
msgs = C.build_messages(L, st, dict(P, quiet_hours=False, local_time="Sat 2:00 PM"), at(14, 0, 21))
check("prompt says quiet hours NO explicitly, with the schedule", "Quiet hours: NO. It is NOT quiet hours" in msgs[1]["content"]
      and "Quiet hours next start Sunday 11:00 PM" in msgs[1]["content"] and "trust the NOW line" in msgs[0]["content"], msgs[1]["content"][:400])
check("prompt says YES in quiet hours", "Quiet hours: YES, it is quiet hours now" in C.build_messages(L, st, dict(P, quiet_hours=True), now)[1]["content"])
st = C.new_state(); st["alpha_backoff_until"] = at(15, 0, 21) + 9999
LX["reply"] = '{"action":"none","params":{},"reason":"weekend"}'
e = C.tick(L, st, at(15, 0, 21), perceive_fn=perceive(dict(P, local_time="Sat 3:00 PM")), camera_fn=lambda L, s, n: [],
           inbox_fn=lambda L, s, n: [], talk_fn=lambda *a: 0)
seen = LX["seen"][-1]["messages"][1]["content"] if LX["seen"] else ""
check("the local 3B gets the same explicit flag (Sat 3 PM: NO)", e["brain"] == "local" and "Quiet hours: NO" in seen, (e.get("brain"), seen[:200]))
check("tick perception carries quiet_hours false on Saturday", e["perception"]["quiet_hours"] is False)

# ---- request_account: plain domain, known TLD, Alpha or hosted only ----
def ra(service, p=P, n=now, s=None):
    return C.validate(L, s or C.new_state(), p, {"action": "request_account", "params": {"service": service, "why": "to keep my code"}}, n)
check("github.com ok", ra("github.com") == ("request_account", {"service": "github.com", "why": "to keep my code"}, "ok"))
check("pinos.world ok", ra("pinos.world")[2] == "ok")
check("WWW.GitHub.COM normalized", ra("WWW.GitHub.COM")[1].get("service") == "www.github.com")
for bad in ("GitHub", "https://github.com", "github.com/login", "me@github.com", "me:pw@github.com", "github.local",
            "github.notatld", "192.168.1.20", "10.0.0.1.com", "git hub.com", "-bad-.com", "github..com", "localhost", "x.c"):
    check("rejected service %r" % bad, ra(bad)[2].startswith("rejected"), ra(bad))
check("local brain cannot ask", "only counts when the Alpha brain or the hosted backup" in ra("github.com", dict(P, brain="local"))[2])
check("unknown brain cannot ask", ra("github.com", {k: v for k, v in P.items() if k != "brain"})[2].startswith("rejected"))
check("hosted backup may ask", ra("github.com", dict(P, brain="hosted"))[2] == "ok")
st = C.new_state(); st["alpha_backoff_until"] = now + 9999
LX["reply"] = '{"action":"request_account","params":{"service":"github.com","why":"to keep my code"},"reason":"want it"}'
e = C.tick(L, st, now, perceive_fn=perceive(P), camera_fn=lambda L, s, n: [], inbox_fn=lambda L, s, n: [], talk_fn=lambda *a: 0)
check("local 3B request_account refused and journaled", e["brain"] == "local" and "only counts when" in e["validator"]
      and "only counts when" in journal_text() and not C.load_account_requests(), e.get("validator"))
st = C.new_state()
PX["reply"] = '{"action":"request_account","params":{"service":"github.com","why":"to keep my code"},"reason":"want it"}'
e = C.tick(L, st, now, perceive_fn=perceive(P), camera_fn=lambda L, s, n: [], inbox_fn=lambda L, s, n: [], talk_fn=lambda *a: 0)
check("Alpha brain request_account accepted (pending)", e["brain"] == "alpha" and e["validator"] == "ok"
      and [r["service"] for r in C.load_account_requests()] == ["github.com"], e.get("validator"))

# ---- message_zack defaults ----
mz = L["actions"]["message_zack"]
check("message_zack: 3 an hour, no daily cap", mz["per_hour"] == 3 and mz["per_day"] is None)
st = C.new_state(); st["recent"] = [[now - 4000 - 900 * i, "message_zack"] for i in range(20)]
msg = {"action": "message_zack", "params": {"text": "Alpha back up."}}
check("20 earlier today, none this hour -> ok", C.validate(L, st, P, msg, now)[2] == "ok")
st["recent"] = [[now - 300 * (i + 1), "message_zack"] for i in range(3)]
check("4th this hour refused", "hourly cap" in C.validate(L, st, P, msg, now)[2])
check("weekday quiet hours refuse it", C.validate(L, C.new_state(), dict(P, quiet_hours=True), msg, now)[2] == "rejected: quiet hours")

# ---- limits command ----
HELPER = os.path.join(SRC, "grokbot-set-cypher-limit")
henv = dict(os.environ, GROKBOT_CYPHER_LIMITS_FILE=LIM, GROKBOT_CYPHER_LIMITS_NOROOT="1", CYPHER_LIB=SRC)
def setlim(*a, env=henv):
    r = subprocess.run([sys.executable, HELPER, *a], capture_output=True, text=True, env=env); return r.returncode, r.stdout + r.stderr
st = C.new_state(); C.limits_watch(L, st, now)
check("no root -> refused", setlim("message_zack", "per_hour", "5", env=dict(henv, GROKBOT_CYPHER_LIMITS_NOROOT="0"))[0] != 0)
rc, out = setlim("message_zack", "per_hour", "5")
check("set message_zack per_hour 5", rc == 0 and "3 -> 5" in out, out)
check("file stays 0644 and valid", stat.S_IMODE(os.stat(LIM).st_mode) == 0o644 and json.load(open(LIM))["actions"]["message_zack"]["per_hour"] == 5)
L2 = C.current_limits(st)
check("cypherd reloads it live (no restart)", L2["actions"]["message_zack"]["per_hour"] == 5)
ch = C.limits_watch(L2, st, now)
check("limits change journaled", ch == ["message_zack per_hour 3 -> 5"] and "limits_changed" in journal_text(), ch)
for args, label in ((("message_zack", "per_hour", "11"), "per_hour over 10"), (("message_zack", "per_day", "51"), "per_day over 50"),
                    (("request_account", "per_day", "none"), "account cap none"), (("request_account", "per_week", "3"), "account per_week raise"),
                    (("message_zack", "per_week", "3"), "unknown key"), (("unlock_door", "per_day", "1"), "unknown action"),
                    (("message_zack", "per_hour", "none"), "none for per_hour"), (("message_zack", "per_hour", "-1"), "negative"),
                    (("message_zack", "per_hour", "2.5"), "fraction")):
    rc, out = setlim(*args)
    check("refused: %s" % label, rc != 0, out)
rc, out = setlim("message_zack", "per_day", "none")
check("per_day none accepted", rc == 0 and json.load(open(LIM))["actions"]["message_zack"]["per_day"] is None, out)
rc, out = setlim("message_zack", "per_day", "50"); rc2, _ = setlim("message_zack", "per_day", "none")
check("per_day 50 then back to none", rc == 0 and rc2 == 0)
cenv = dict(henv, CYPHER_NO_SUDO="1", CYPHER_SET_LIMIT=HELPER, CYPHER_DAEMON=os.path.join(SRC, "cypherd.py"), CYPHER_NO_SYSTEMCTL="1")
pr = subprocess.run([os.path.join(SRC, "grokbot-cypher"), "limits", "set", "message_zack", "per_hour", "3"], capture_output=True, text=True, env=cenv)
check("grokbot-cypher limits set forwards to the helper", pr.returncode == 0 and "5 -> 3" in pr.stdout, pr.stdout + pr.stderr)
pr = subprocess.run([os.path.join(SRC, "grokbot-cypher"), "limits"], capture_output=True, text=True, env=cenv)
check("grokbot-cypher limits shows caps and quiet hours", pr.returncode == 0 and "message_zack" in pr.stdout and "per_day none" in pr.stdout
      and "none on Fri, Sat nights" in pr.stdout, pr.stdout + pr.stderr)
bad = json.load(open(LIM)); bad["actions"]["show_note"]["per_day"] = "lots"
try: C.validate_limits(bad); check("non-number cap refused on load", False)
except C.ConfigError: check("non-number cap refused on load", True)
L = C.current_limits(C.new_state())

# ---- gridwatch ----
PX["lease"]["expires"] = now + 3600
NT["gh"] = [{"sha": "d0f2f51aaaabbbb", "commit": {"message": "rpi5 cypher phase 4b: one mind token=%s see https://x.example 192.168.12.126\nbody" % TOKEN,
                                                   "committer": {"date": "2026-11-15T18:02:00Z"}}}]
st = C.new_state(); st["cam_feed"] = {"ok": True, "at": now}
st["cam_log"] = [{"time": "13:22", "camera": "front_door", "kind": "arrival_end", "names": ["Zack"]}]
g = C.grid_refresh(L, st, now, repo=True)
check("grid: Alpha up, proxy ok, mind on the deck", g["alpha"] == "up" and g["proxy"] == "ok" and g["mind"] == "deck", g)
check("grid: standby's last thought time", g["standby"].startswith("2026-11-16T10:09"))
check("grid: repo commit via the public API, branch from limits", g["repos"][0]["sha"] == "d0f2f51" and "feat%2Frpi5-next-flash" in NT["gh_url"]
      and NT["gh_url"].startswith("https://api.github.com/repos/gearhed90/grokbotos/commits"), g["repos"])
summ = C.grid_summary(st, now)
check("grid summary: human, first names only, Eastern commit time", "Alpha up" in summ and "front_door arrival end (Zack)" in summ
      and "1:02 PM" in summ, summ)
check("grid summary carries no token, link or address", not any(x in summ for x in SECRETS), summ)
snap = C.dash_snapshot(L, st, True, now)
check("snapshot has the grid report, scrubbed", snap["grid"]["alpha"] == "up" and snap["grid"]["repos"][0][1] == "d0f2f51"
      and not any(x in json.dumps(snap) for x in SECRETS), snap.get("grid"))
PX["reply"] = '{"action":"check_grid","params":{},"reason":"Zack is away; keep track of the grid"}'
st = C.new_state(); st["drives"].update(boredom=0.8, curiosity=0.7)
e = C.tick(L, st, now, perceive_fn=perceive(dict(P, presence="away")), camera_fn=lambda L, s, n: [], inbox_fn=lambda L, s, n: [], talk_fn=lambda *a: 0)
check("check_grid tick: ok, found the report", e["validator"] == "ok" and e["result"] == "ok" and "Alpha up" in (e.get("found") or ""), e)
check("check_grid eases boredom and curiosity", st["drives"]["boredom"] < 0.8 and st["drives"]["curiosity"] < 0.7)
check("next prompt sees the report", "check_grid" in C.build_messages(L, st, P, now + 60)[1]["content"])
check("journal has no secrets from the grid", not any(x in journal_text() for x in SECRETS))
st["recent"] += [[now - 60 * i, "check_grid"] for i in range(1, 4)]
check("check_grid hourly cap (4)", "hourly cap" in C.validate(L, st, P, {"action": "check_grid", "params": {}}, now)[2])
PX["up"] = False
Ld = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"})); Ld["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % free_port()]
Ld = C.validate_limits(Ld); std = C.new_state(); C.grid_refresh(Ld, std, now)
check("Alpha unreachable -> 'down', and the prompt flags it", std["grid"]["alpha"] == "down" and "grid trouble" in C.grid_lines(std, now + 10), std["grid"])
LA = A.current_limits(A.new_state())
check("Alpha standby has no check_grid (deck only)", "check_grid" not in A.allowed_actions(LA))
L0g = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"})); L0g["grid"]["enabled"] = False
check("grid off -> check_grid blocked", C.blocked(C.validate_limits(L0g), C.new_state(), P, "check_grid", now) == "grid checks off")

# ---- self-tuning ----
TUN = C.TUN_FILE
def lim_mtime(): return os.stat(LIM).st_mtime_ns
m0 = lim_mtime()
day = "2026-11-15"
D = os.path.join(T, "data", "journal")
with open(os.path.join(D, day + ".jsonl"), "a") as f:
    for i in range(4):
        f.write(json.dumps({"ts": "%sT1%d:00:00-0500" % (day, i), "tick": i, "mood": "restless", "brain": "alpha",
                            "choice": {"action": "journal_thought", "params": {"text": "t%d" % i}}, "reason": "r"}) + "\n")
tune = {"drift": {"boredom": -0.5, "bogus": 1}, "effect_scale": {"boredom": 0.3}, "bias": {"check_grid": 0.4, "message_zack": 1},
        "caps": {"show_note": {"per_hour": 2}, "message_zack": {"per_hour": 9}, "look_up": {"per_hour": 9}},
        "quiet_hours": {"default": None}, "reason": "restless afternoons; grid checks help"}
PX["reply"] = json.dumps({"memories": ["a calm day"], "add_notes": [], "drop_notes": [], "drift_adjust": {"curiosity": 0.02}, "tune": tune, "reason": "ok"})
st = C.new_state()
before_tun = C.load_tunables(L)
s1 = C.maybe_sleep(L, st, at(4, 5, 16))
props = C.load_proposals()
check("sleep made one pending proposal (Alpha brain)", s1 and s1["tuning"]["proposed"] == 1 and props[0]["status"] == "pending", s1 and s1.get("tuning"))
paths = {c["path"]: c for c in props[0]["changes"]}
check("at most 3 changes, each clamped to its step", len(props[0]["changes"]) == 3
      and paths["drift.boredom"]["after"] == round(C.DEFAULT_DRIFT["boredom"] - 0.02, 4)
      and paths["effect.boredom"]["after"] == 1.1 and paths["bias.check_grid"]["after"] == 0.25, props[0]["changes"])
check("hard limits and unknowns refused (message_zack caps/bias, quiet hours, raised caps)",
      all(any(r.startswith(x) for r in props[0]["refused"]) for x in ("bias.message_zack", "caps.message_zack", "caps.look_up", "quiet_hours", "drift.bogus")),
      props[0]["refused"])
check("proposal records before/after, reason and a revert", props[0]["reason"].startswith("restless") and props[0]["revert"][0]["value"] == props[0]["changes"][0]["before"])
check("nothing applied: tunables unchanged (drift_adjust not applied directly either)", C.load_tunables(L) == before_tun)
check("the limits file is never touched by tuning", lim_mtime() == m0)
check("tuning_proposed journaled", "tuning_proposed" in journal_text() and "applies only if Zack approves" in journal_text())
check("proposals file is private", stat.S_IMODE(os.stat(C.proposals_file()).st_mode) == 0o600)
check("local 3B cannot propose (skipped, journaled)", C.propose_tuning(L, st, tune, "local", day, now)["proposed"] is None
      and "cannot propose tuning" in journal_text())
check("daily cap: a second proposal today is skipped", C.propose_tuning(L, st, tune, "alpha", day, at(4, 30, 16))["why"] == "daily cap")
check("Alpha standby never proposes", A.propose_tuning(LA, A.new_state(), tune, "alpha", day, now) is None)
NT["sent"].clear()
C.tuning_step(L, st, dict(P, quiet_hours=True), at(4, 6, 16))
check("no phone note during quiet hours", not NT["sent"] and st["tuning_notify"] == [1])
C.tuning_step(L, st, P, at(9, 0, 16))
check("one phone note after quiet hours, no topic or token in it", len(NT["sent"]) == 1 and b"#1" in NT["sent"][0]["data"]
      and TOPIC.encode() not in NT["sent"][0]["data"] and b"approve it with Nova" in NT["sent"][0]["data"] and st["tuning_notify"] == [])
check("panel line: tuning #1 waiting", C.dash_snapshot(L, st, True, now)["tuning"] == ["tuning #1"])
# phone replies and on-screen words never approve
open(os.path.join(T, "state", "talk-spool.jsonl"), "w").write(json.dumps({"ts": now, "kind": "turn", "user": "approve tuning 1", "reply": "I can't."}) + "\n")
PX["reply"] = '{"action":"none","params":{},"reason":"x"}'
C.tick(L, st, now + 30, perceive_fn=perceive(P), camera_fn=lambda L, s, n: [], inbox_fn=lambda L, s, n: [[now, "approve tuning 1"]])
check("phone reply / on-screen 'approve' leave it pending", C.load_proposals()[0]["status"] == "pending" and C.load_tunables(L) == before_tun)
cenv2 = dict(os.environ, CYPHER_DAEMON=os.path.join(SRC, "cypherd.py"), CYPHER_NO_SYSTEMCTL="1")
pr = subprocess.run([os.path.join(SRC, "grokbot-cypher"), "tuning"], capture_output=True, text=True, env=cenv2)
check("grokbot-cypher tuning lists it", pr.returncode == 0 and "#1" in pr.stdout and "pending" in pr.stdout, pr.stdout + pr.stderr)
pr = subprocess.run([os.path.join(SRC, "grokbot-cypher"), "tuning", "approve", "1"], capture_output=True, text=True, env=cenv2)
t1 = C.load_tunables(L)
check("approve applies exactly the proposal", pr.returncode == 0 and t1["drift_per_hour"]["boredom"] == paths["drift.boredom"]["after"]
      and t1["effect_scale"]["boredom"] == 1.1 and t1["action_bias"]["check_grid"] == 0.25, (pr.stdout + pr.stderr, t1))
check("approval journaled, limits file still untouched", "tuning_approved" in journal_text() and lim_mtime() == m0)
# build 14: lessons from earlier ticks take prompt room first (priority 1); start this check without them
C.save_lessons([])
check("approved leaning reaches the prompt", "toward check_grid" in C.build_messages(L, C.new_state(), P, now)[1]["content"])
check("effect weight scales action effects", C.scaled({"boredom": -0.1}, t1)["boredom"] == -0.1 * 1.1)
check("approve twice refused", C.cli(["tuning", "approve", "1"]) == 1)
pr = subprocess.run([os.path.join(SRC, "grokbot-cypher"), "tuning", "revert", "1"], capture_output=True, text=True, env=cenv2)
check("revert puts the values back", pr.returncode == 0 and C.load_tunables(L) == before_tun, (pr.stdout, C.load_tunables(L)))
# soft caps: only lower, applied through approval
rows = C.load_proposals()
rec = {"id": 2, "ts": C.iso(now), "epoch": now - 2 * 86400, "day": day, "brain": "alpha", "reason": "fewer notes",
       "changes": C.tuning_changes(L, {"caps": {"show_note": {"per_hour": 2}}})[0], "status": "pending"}
rows.append(rec); C.save_proposals(rows)
check("soft cap proposal lowers show_note 6 -> 2", rec["changes"] == [{"path": "cap.show_note.per_hour", "before": 6, "after": 2}], rec["changes"])
with contextlib.redirect_stdout(io.StringIO()): C.cli(["tuning", "approve", "2"])
check("approved soft cap in force", C.eff_spec(L, "show_note")["per_hour"] == 2 and L["actions"]["show_note"]["per_hour"] == 6)
st2 = C.new_state(); st2["recent"] = [[now - 100, "show_note"], [now - 200, "show_note"]]
check("show_note refused at the soft cap", "hourly cap" in C.blocked(L, st2, P, "show_note", now))
with contextlib.redirect_stdout(io.StringIO()): C.cli(["tuning", "revert", "2"])
check("revert drops the soft cap", C.eff_spec(L, "show_note")["per_hour"] == 6)
raw = json.load(open(TUN)); raw.setdefault("caps", {})["message_zack"] = {"per_hour": 1}; raw["caps"]["look_up"] = {"per_hour": 50}
C.write_json(TUN, raw)
check("a hand-edited tunables file cannot cap message_zack or raise a cap", C.eff_spec(L, "message_zack")["per_hour"] == 3
      and C.eff_spec(L, "look_up")["per_hour"] == L["actions"]["look_up"]["per_hour"])
# stale approve, deny, expire
rows = C.load_proposals()
rows.append({"id": 3, "ts": C.iso(now), "epoch": now - 3 * 86400, "day": day, "brain": "hosted", "reason": "r", "status": "pending",
             "changes": [{"path": "drift.focus", "before": -0.9, "after": -0.88}]})
rows.append({"id": 4, "ts": C.iso(now), "epoch": now - 9 * 86400, "day": day, "brain": "hosted", "reason": "r", "status": "pending",
             "changes": [{"path": "drift.focus", "before": -0.04, "after": -0.02}]})
C.save_proposals(rows)
with contextlib.redirect_stdout(io.StringIO()) as b: rc = C.cli(["tuning", "approve", "3"])
check("stale proposal (values moved) not applied", rc == 1 and "not applied" in b.getvalue())
with contextlib.redirect_stdout(io.StringIO()): rc = C.cli(["tuning", "deny", "3"])
check("deny", rc == 0 and C.load_proposals()[2]["status"] == "denied")
C.tuning_step(L, C.new_state(), P, now)
check("pending over 7 days expires", next(r for r in C.load_proposals() if r["id"] == 4)["status"] == "expired" and "tuning_expired" in journal_text())
Ltoff = json.loads(json.dumps({k: v for k, v in L.items() if k != "_quiet_nights"})); Ltoff["phase_max"] = 4
Ltoff = C.validate_limits(Ltoff)
check("phase 4 limits -> no tuning", not C.tuning_on(Ltoff) and C.propose_tuning(Ltoff, st, tune, "alpha", day, now) is None)
src = open(os.path.join(SRC, "cypherd.py")).read()
check("tuning code never names the limits file as a target", "write_json(LIMITS_FILE" not in src and "open(LIMITS_FILE, \"w\"" not in src)

# ---- panels: Eastern clock without touching TZ ----
try:
    import cairo  # noqa: F401
    spec = importlib.util.spec_from_file_location("cypher_panels", os.path.join(SRC, "cypher_panels.py"))
    Pn = importlib.util.module_from_spec(spec)
    os.environ["TZ"] = "UTC"; time.tzset()
    spec.loader.exec_module(Pn)
    check("panel clock is Eastern even when the process is UTC", Pn.clock_text(1763316000) == "Sun 1:00 PM", Pn.clock_text(1763316000))
    os.environ["TZ"] = "America/New_York"; time.tzset()
    out = os.environ.get("CYPHER_DASH_PREVIEW5") or os.path.join(T, "p5.png")
    snap = C.dash_snapshot(L, st, True, now); snap["epoch"] = now
    snap["grid"] = {"alpha": "up", "proxy": "ok", "mind": "deck", "standby": "10:09", "cams": "ok", "checked": "1:55 PM",
                    "repos": [["grokbotos", "d0f2f51", "1:02 PM", "rpi5 cypher phase 4b: one mind - the avatar is Cypher"]]}
    Pn.render_png(out, snap, now=now)
    check("renders the grid report frame", os.path.getsize(out) > 1000)
    print("preview:", out)
except ImportError:
    print("SKIP panel tests (no pycairo here)")
print("phase 5 tests: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
