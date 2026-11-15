#!/usr/bin/env python3
"""Phase 2.1 + phase 3 tests for cypherd: an honest manifest (caps, refusals,
mood-gated colors), honest camera lines, and the phone / screen glance /
look-up actions. Fake proxy on localhost; no display, root or network."""
import importlib.util, json, os, socket, sys, tempfile, threading, time
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

PX = {"reply": '{"action":"none","reason":"x"}', "seen": [], "vision": [], "vcode": 200, "desc": "A terminal running htop and a CAD window."}
class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._j(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/vision/describe":
            PX["vision"].append(body)
            return self._j(PX["vcode"], {"description": PX["desc"]} if PX["vcode"] == 200 else {"busy": "camera_busy"})
        PX["seen"].append(body)
        self._j(200, {"model": "fake", "choices": [{"message": {"content": PX["reply"]}}], "usage": {}})
port = free_port()
srv = ThreadingHTTPServer(("127.0.0.1", port), Proxy); threading.Thread(target=srv.serve_forever, daemon=True).start()

T = tempfile.mkdtemp(); TOKEN = "k" * 40; TOPIC = "cypher-" + "T0p1cSecretXyz_abcdefgh"
for n, v in (("token", TOKEN), ("topic", TOPIC)):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
L0 = json.load(open(os.path.join(SRC, "cypher-limits.json")))
L0["brain"]["primary_urls"] = ["http://127.0.0.1:%d" % port]; L0["brain"]["primary_url"] = L0["brain"]["primary_urls"][0]
L0["brain"]["local"]["enabled"] = False; L0["brain"]["hosted_backup"]["enabled"] = False
L0["failover"]["enabled"] = False; L0["camera"]["enabled"] = False; L0["sleep"]["enabled"] = False
L0["grid"]["enabled"] = False      # gridwatch has its own tests (test_cypherd_phase5.py)
L0["ntfy"]["inbox"]["enabled"] = False      # phase 4's reply inbox has its own tests (test_cypherd_phase4.py)
with open(os.path.join(T, "limits.json"), "w") as f: json.dump(L0, f)
os.environ.update(CYPHER_LIMITS=os.path.join(T, "limits.json"), CYPHER_LIMITS_INSECURE_OK="1",
                  CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"), CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"),
                  CYPHER_NTFY_TOPIC_FILE=os.path.join(T, "topic"), CYPHER_CONFIG_DIR=os.path.join(T, "cfg"),
                  CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_DATA_DIR=os.path.join(T, "data"),
                  CYPHER_PERSONA=os.path.join(SRC, "persona.md"), CYPHER_DRY_RUN="1", TZ="America/New_York",
                  XDG_RUNTIME_DIR=os.path.join(T, "run"))
os.makedirs(os.path.join(T, "run"), exist_ok=True)
def load(tag, host="deck"):
    os.environ["CYPHER_HOST"] = host
    spec = importlib.util.spec_from_file_location("cypherd_" + tag, os.path.join(SRC, "cypherd.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
C = load("p3")
L = C.current_limits(C.new_state())
def at(h, m=0, day=16):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))     # Mon Nov 16 2026
P = {"local_time": "Mon 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": [], "brain": "alpha"}
def manifest(st, p=P, now=None):
    return C.build_messages(L, st, dict(p), now or at(14))[0]["content"].split("Manifest:")[1]

# ---- 2.1: the manifest only offers what would pass ----
st = C.new_state(); now = at(14)
m = manifest(st)
check("fresh state offers all phase-3 actions", all(a in m for a in ("journal_thought", "show_note", "set_avatar_color",
                                                                  "message_zack", "glance_screen", "look_up", "request_account")), m)
st["recent"] = [[now - 600, "set_avatar_color"], [now - 300, "set_avatar_color"]]
check("color capped -> not in the manifest", "set_avatar_color" not in manifest(st))
check("validator refuses it with the same words", C.validate(L, st, P, {"action": "set_avatar_color", "params": {"color": "red"}}, now)[2]
      == "rejected: set_avatar_color hourly cap")
st["recent"] = [[now - 3700, "set_avatar_color"], [now - 300, "set_avatar_color"]]
check("oldest change over an hour old -> offered again", "set_avatar_color" in manifest(st))
st = C.new_state()
for k, v in (("muted", True), ("dnd", True), ("quiet_hours", True), ("presence", "away")):
    check("show_note left out when %s=%s" % (k, v), "show_note" not in manifest(st, dict(P, **{k: v})))
st["recent"] = [[now - 7200 - 60 * i, "show_note"] for i in range(12)]
check("show_note daily cap -> left out", "show_note" not in manifest(st))
check("camera tick offers only journal/none", sorted(l.split(" - ")[0][2:] for l in manifest(C.new_state(), dict(P, camera=[{"kind": "family", "time": "2026-11-15 09:00:00", "camera": "front_door"}])).strip().splitlines())
      == ["journal_thought", "none"])

# ---- 2.1: refusals show in last_actions ----
st = C.new_state(); st["recent"] = [[now - 600, "set_avatar_color"], [now - 300, "set_avatar_color"]]
PX["reply"] = '{"action":"set_avatar_color","params":{"color":"gray"},"reason":"mood"}'
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
check("capped color attempt is refused", e["validator"] == "rejected: set_avatar_color hourly cap", e.get("validator"))
check("last_actions shows the refusal", st["last_actions"][-1] == "set_avatar_color gray (refused: hourly cap)", st["last_actions"])
PX["reply"] = '{"action":"journal_thought","params":{"text":"quiet grid"},"reason":"x"}'
st["last_sig"] = None
C.tick(L, st, now + 60, perceive_fn=lambda L, n: dict(P, focused_app="x"), camera_fn=lambda L, s, n: [])
user = PX["seen"][-1]["messages"][1]["content"]
check("next prompt shows the refusal", "set_avatar_color gray (refused: hourly cap)" in user, user)

# ---- 2.1: color only on a real mood change ----
st = C.new_state(); st["mood"] = {"label": "idle"}
V = lambda ch, n=now: C.validate(L, st, P, ch, n)
check("first color ok", V({"action": "set_avatar_color", "params": {"color": "gray"}})[2] == "ok")
PX["reply"] = '{"action":"set_avatar_color","params":{"color":"gray"},"reason":"x"}'
st["drives"] = {"energy": 0.5, "curiosity": 0.5, "social": 0.5, "boredom": 0.5, "focus": 0.5}
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
lab = st["mood"]["label"]
check("successful color remembers color and mood", st["avatar_color"] == "gray" and st["color_mood"] == lab, (st["avatar_color"], st["color_mood"]))
check("same mood -> color refused", V({"action": "set_avatar_color", "params": {"color": "green"}})[2] == "rejected: no mood change since the last color")
check("same mood -> color left out of the manifest", "set_avatar_color" not in manifest(st))
st["mood"] = {"label": "curious" if lab != "curious" else "idle"}
check("mood changed -> same color still refused", V({"action": "set_avatar_color", "params": {"color": "gray"}})[2] == "rejected: already gray")
check("mood changed -> new color ok", V({"action": "set_avatar_color", "params": {"color": "teal"}})[2] == "ok")
check("color is a small boredom outlet", C.ACTION_EFFECTS["set_avatar_color"]["boredom"] == -0.02 and
      C.ACTION_EFFECTS["journal_thought"]["boredom"] < C.ACTION_EFFECTS["set_avatar_color"]["boredom"])
check("color memory survives a restart", all(k in C.new_state() for k in ("avatar_color", "color_mood", "found")))

# ---- 2.1: honest camera lines ----
C.L_cam = None
line = C.camera_line([{"time": "2026-11-15 09:17:37", "camera": "front_door", "kind": "unconfirmed", "guess": "vehicle"}])
check("unconfirmed line says nobody was identified", "unconfirmed motion (detector guess: vehicle; not checked, nobody identified)" in line, line)
ev = C.clean_event({"seq": 3, "time": "2026-11-15 09:17:37", "camera": "front_door", "kind": "nothing", "reason": "camera pan, parked cars only"})
check("nothing event keeps a plain reason", ev and ev["reason"] == "camera pan, parked cars only", ev)
check("free-text reasons are dropped", "reason" not in C.clean_event({"seq": 3, "time": "2026-11-15 09:17:37", "camera": "front_door",
                                                                   "kind": "nothing", "reason": "Zack's car http://x"}))
check("guess outside the list dropped", "guess" not in C.clean_event({"seq": 1, "time": "2026-11-15 09:17:37", "camera": "front_door", "kind": "unconfirmed", "guess": "Zack"}))
Lc = json.loads(json.dumps(L)); Lc["camera"]["enabled"] = True; Lc["camera"]["react_kinds"].append("nothing")
tnow = time.mktime(time.strptime("2026-11-15 09:20:00", "%Y-%m-%d %H:%M:%S"))
evs = [{"seq": 1, "time": "2026-11-15 09:17:37", "camera": "front_door", "kind": "nothing", "reason": "camera pan"},
       {"seq": 2, "time": "2026-11-15 09:18:00", "camera": "front_door", "kind": "family", "names": ["Zack"]},
       {"seq": 3, "time": "2026-11-15 09:19:00", "camera": "front_door", "kind": "unconfirmed", "guess": "person"}]
real_api = C.alpha_api
C.alpha_api = lambda L, m, path, body=None, timeout=6: (200, {"events": evs, "last_seq": 3})
got = C.camera_step(Lc, {"cam_seq": 0}, tnow)
C.alpha_api = real_api
check("nothing events never reach a tick (even if listed)", [e["kind"] for e in got] == ["family", "unconfirmed"], got)
check("shipped react_kinds skip nothing, include unconfirmed", "nothing" not in L["camera"]["react_kinds"] and "unconfirmed" in L["camera"]["react_kinds"])
cm = C.build_messages(L, C.new_state(), dict(P, camera=got[1:]), now)[1]["content"]
check("camera prompt forbids inventing doors and identities", "Never invent doors opening" in cm and "do not guess who it was" in cm, cm)

# ---- phase 3: message_zack ----
st = C.new_state()
check("message ok", C.validate(L, st, P, {"action": "message_zack", "params": {"text": "Alpha proxy down 2h."}}, now)[2] == "ok")
check("message over 200 refused", "over 200" in C.validate(L, st, P, {"action": "message_zack", "params": {"text": "x" * 201}}, now)[2])
check("message in quiet hours refused", C.validate(L, st, dict(P, quiet_hours=True), {"action": "message_zack", "params": {"text": "hi"}}, now)[2] == "rejected: quiet hours")
check("message works while Zack is away (it is his phone)", C.validate(L, st, dict(P, presence="away"), {"action": "message_zack", "params": {"text": "hi"}}, now)[2] == "ok")
st["recent"] = [[now - 600 * (i + 1), "message_zack"] for i in range(3)]
check("4th message in an hour refused (per_hour 3)", "hourly cap" in C.validate(L, st, P, {"action": "message_zack", "params": {"text": "hi"}}, now)[2])
st["recent"] = [[now - 4000 - 1200 * i, "message_zack"] for i in range(12)]
check("no daily cap: 13th message today allowed outside the hour", C.validate(L, st, P, {"action": "message_zack", "params": {"text": "hi"}}, now)[2] == "ok"
      and L["actions"]["message_zack"]["per_day"] is None and L["actions"]["message_zack"]["per_hour"] == 3)
check("Friday 11:30 PM not quiet -> message allowed (no quiet hours Fri/Sat)",
      not C.in_quiet_hours(L, at(23, 30, 20)) and C.validate(L, C.new_state(), dict(P, quiet_hours=C.in_quiet_hours(L, at(23, 30, 20))),
                                                             {"action": "message_zack", "params": {"text": "hi"}}, at(23, 30, 20))[2] == "ok")
os.rename(os.path.join(T, "topic"), os.path.join(T, "topic.off"))
check("no topic file -> message_zack left out", "message_zack" not in manifest(C.new_state()))
os.rename(os.path.join(T, "topic.off"), os.path.join(T, "topic"))
sent = []
def fake_http(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    sent.append({"url": url, "data": data, "headers": headers, "hosts": hosts}); return 200, b"{}"
real_http = C._http; C._http = fake_http
check("send_ntfy posts to ntfy.sh/<topic>", C.send_ntfy(L, "hello") == "ok" and sent[-1]["url"] == "https://ntfy.sh/" + TOPIC
      and sent[-1]["data"] == b"hello" and sent[-1]["hosts"] == ["ntfy.sh"] and sent[-1]["headers"]["Title"] == "Cypher")
C.DRY_RUN = False
st = C.new_state(); PX["reply"] = '{"action":"message_zack","params":{"text":"Alpha has been unreachable for an hour."},"reason":"worth it"}'
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
check("message_zack tick sends once", e["result"] == "ok" and len(sent) == 2, e)
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["ntfy-test"])
check("ntfy-test sends one test message", rc == 0 and "sent" in buf.getvalue() and len(sent) == 3 and b"Test from Cypher" in sent[-1]["data"], buf.getvalue())
check("topic never printed", TOPIC not in buf.getvalue())
C.DRY_RUN = True; C._http = real_http
try: C._http("http://ntfy.sh/x", data=b"x", hosts=["ntfy.sh"]); check("plain http refused", False)
except ValueError: check("plain http refused", True)
try: C._http("https://evil.example/x", hosts=["en.wikipedia.org"]); check("host off the allowlist refused", False)
except ValueError: check("host off the allowlist refused", True)

# ---- phase 3: look_up ----
st = C.new_state()
check("look_up ok", C.validate(L, st, P, {"action": "look_up", "params": {"topic": "Raspberry Pi"}}, now)[:2] == ("look_up", {"topic": "Raspberry Pi"}))
for bad in ("", "x" * 61, "http://evil.com", "a/b?c=1", None):
    check("bad topic refused: %r" % (bad,), "plain topic" in C.validate(L, st, P, {"action": "look_up", "params": {"topic": bad}}, now)[2])
st["recent"] = [[now - 5000 * (i + 1), "look_up"] for i in range(6)]
check("7th look-up in a day refused", "daily cap" in C.validate(L, st, P, {"action": "look_up", "params": {"topic": "Tank"}}, now)[2])
got_urls = []
def wiki(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    got_urls.append((url, hosts))
    if "Nowhere" in url: return 404, b""
    return 200, json.dumps({"extract": "The Raspberry Pi is a series of small single-board computers. See https://x.y for more."}).encode()
C._http = wiki
st = C.new_state(); PX["reply"] = '{"action":"look_up","params":{"topic":"Raspberry Pi 5"},"reason":"my body"}'
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
check("look_up fetches the Wikipedia summary API", got_urls[-1][0] == "https://en.wikipedia.org/api/rest_v1/page/summary/Raspberry_Pi_5?redirect=true"
      and got_urls[-1][1] == ["en.wikipedia.org"], got_urls)
check("finding journaled (URLs stripped)", e.get("found", "").startswith("The Raspberry Pi is a series") and "https" not in e["found"], e)
check("last_actions names the topic", st["last_actions"][-1] == "look_up Raspberry Pi 5", st["last_actions"])
PX["reply"] = '{"action":"none","reason":"x"}'; st["last_sig"] = None
C.tick(L, st, now + 60, perceive_fn=lambda L, n: dict(P, focused_app="y"), camera_fn=lambda L, s, n: [])
check("next prompt carries the finding", "you recently found out: " in PX["seen"][-1]["messages"][1]["content"]
      and "single-board" in PX["seen"][-1]["messages"][1]["content"])
check("not found is a result, not an error", C.do_look_up(L, st, "Nowhere Land") == "not found")
C._http = real_http

# ---- phase 3: glance_screen ----
grabs = []
def fake_grab(path, S):
    grabs.append(path)
    with open(path, "wb") as f: f.write(b"\xff\xd8\xff" + b"0" * 2000)
    return True
C._grab_screen = fake_grab
st = C.new_state(); PX["reply"] = '{"action":"glance_screen","params":{},"reason":"what is he doing"}'
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
check("glance described by Alpha's proxy", e["result"] == "ok" and e.get("found") == PX["desc"], e)
check("image went only to /v1/vision/describe as base64 jpeg", len(PX["vision"]) == 1 and PX["vision"][0]["mime"] == "image/jpeg"
      and PX["vision"][0]["image_b64"].startswith("/9j/"))
check("screenshot deleted right after", grabs and not os.path.exists(grabs[-1]))
check("glance never offered when Zack is away", "glance_screen" not in manifest(C.new_state(), dict(P, presence="locked")))
check("private window -> no glance", C.validate(L, C.new_state(), dict(P, window_title="Bitwarden - Passwords"), {"action": "glance_screen"}, now)[2] == "rejected: private window")
st = C.new_state(); st["recent"] = [[now - 100 * (i + 1), "glance_screen"] for i in range(3)]
check("4th glance in an hour refused", "hourly cap" in C.validate(L, st, P, {"action": "glance_screen"}, now)[2])
PX["vcode"] = 503
r = C.do_glance(L, C.new_state(), dict(P))
check("busy Alpha -> glance fails, no fallback", r == "glance failed: camera_busy" and not os.path.exists(grabs[-1]), r)
check("no image ever sent to a chat brain", not any("image" in json.dumps(b) for b in PX["seen"]))
PX["vcode"] = 200

# ---- phase 3: request_account ----
st = C.new_state(); now = at(14)
ok_ch = {"action": "request_account", "params": {"service": "pinos.world", "why": "so I can visit Pino's world"}}
check("request_account ok", C.validate(L, st, P, ok_ch, now) == ("request_account", {"service": "pinos.world", "why": "so I can visit Pino's world"}, "ok"))
check("request allowed while Zack is away", C.validate(L, st, dict(P, presence="away"), ok_ch, now)[2] == "ok")
check("request in quiet hours refused", C.validate(L, st, dict(P, quiet_hours=True), ok_ch, now)[2] == "rejected: quiet hours")
check("request left out of the manifest in quiet hours", "request_account" not in manifest(st, dict(P, quiet_hours=True)))
check("empty service refused", "service name" in C.validate(L, st, P, {"action": "request_account", "params": {"service": "  ", "why": "because"}}, now)[2])
check("empty why refused", "needs a why" in C.validate(L, st, P, {"action": "request_account", "params": {"service": "GitHub", "why": ""}}, now)[2])
check("service over 40 refused", "service name" in C.validate(L, st, P, {"action": "request_account", "params": {"service": "x"*41, "why": "because"}}, now)[2])
check("why over 160 refused", "needs a why" in C.validate(L, st, P, {"action": "request_account", "params": {"service": "GitHub", "why": "y"*161}}, now)[2])
# rejection rules: password, house/camera words, URLs with credentials, the email itself
for label, svc, why in (
    ("password in why", "GitHub", "I need a password manager"),
    ("password in service", "PasswordApp", "to try it"),
    ("house word door", "GitHub", "so I can unlock the front door logs"),
    ("house word camera", "cameras-r-us", "to archive clips"),
    ("cred URL user:pass", "GitHub", "sign in at https://me:secret@evil.example/x"),
    ("cred URL user@", "GitHub", "see https://admin@evil.example/signup"),
    ("cred URL query password", "GitHub", "link https://example.com/a?password=hunter2"),
    ("email in why", "Pino", "use s4j6vbnk+cypher@mail.grokbot.com please"),
):
    v = C.validate(L, st, P, {"action": "request_account", "params": {"service": svc, "why": why}}, now)[2]
    check("rejected: %s" % label, "cannot mention passwords, house controls or credential URLs" in v, v)
# caps: 1/day, 2/week; recent kept long enough for the week
st["recent"] = [[now - 3600, "request_account"]]
check("2nd request the same day refused", "daily cap" in C.validate(L, st, P, ok_ch, now)[2])
check("daily cap leaves request out of the manifest", "request_account" not in manifest(st, now=now))
st["recent"] = [[now - 90000, "request_account"]]  # a bit over a day ago
check("next day, weekly room left -> ok", C.validate(L, st, P, ok_ch, now)[2] == "ok")
st["recent"] = [[now - 90000, "request_account"], [now - 200000, "request_account"]]
check("3rd request in a week refused", "weekly cap" in C.validate(L, st, P, ok_ch, now)[2])
st["recent"] = [[now - (C.WEEK_S + 60), "request_account"], [now - 200000, "request_account"]]
check("oldest over a week old -> weekly cap lifts", C.validate(L, st, P, ok_ch, now)[2] == "ok")
# ntfy success, failure keeps pending, does not consume message_zack, no email in outbound
sent = []
def fake_ntfy(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    sent.append({"url": url, "data": data, "headers": headers}); return 200, b"{}"
real_http = C._http; C._http = fake_ntfy
# start from a clean requests file (STATE_DIR is the temp dir)
req_path = C.requests_file()
if os.path.exists(req_path): os.remove(req_path)
r = C.do_request_account(L, C.new_state(), {"service": "pinos.world", "why": "so I can visit Pino"})
rows = C.load_account_requests()
check("execute writes a pending request", r == "ok" and len(rows) == 1 and rows[0]["status"] == "pending"
      and rows[0]["service"] == "pinos.world" and rows[0]["id"] == 1, (r, rows))
check("ntfy body matches the asked wording and has no email",
      sent and sent[-1]["data"] == b"Cypher asks for an account: pinos.world - so I can visit Pino. Reply to Nova to approve."
      and C.ACCOUNT_EMAIL.encode() not in sent[-1]["data"] and b"mail.grokbot.com" not in sent[-1]["data"],
      sent[-1]["data"] if sent else None)
# journal event from execute
Jlines = []
jd = os.path.join(T, "data", "journal")
for f in os.listdir(jd):
    Jlines += open(os.path.join(jd, f)).read().splitlines()
ev = [json.loads(x) for x in Jlines if "account_request" in x]
check("journal has an account_request event", ev and ev[-1].get("event") == "account_request" and ev[-1].get("status") == "pending"
      and ev[-1].get("service") == "pinos.world" and C.ACCOUNT_EMAIL not in json.dumps(ev[-1]), ev[-1] if ev else None)
# ntfy failure keeps pending
def boom(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    sent.append({"url": url, "data": data}); raise ConnectionError("down")
C._http = boom
r = C.do_request_account(L, C.new_state(), {"service": "Wikipedia", "why": "a login for look-ups that need an account"})
rows = C.load_account_requests()
check("ntfy failure still leaves a pending entry", r.startswith("asked; phone failed") and len(rows) == 2
      and rows[-1]["service"] == "Wikipedia" and rows[-1]["status"] == "pending", (r, rows[-1] if rows else None))
# message_zack budget is independent
st = C.new_state()
# two request_account already happened via execute, not via tick, so recent is empty
check("request_account ntfy does not consume message_zack's cap",
      C.validate(L, st, P, {"action": "message_zack", "params": {"text": "Alpha is down."}}, now)[2] == "ok")
# a real tick should append request_account (not message_zack) to recent
C._http = fake_ntfy
before = len(sent)
PX["reply"] = '{"action":"request_account","params":{"service":"github.com","why":"so I can file issues on the tank firmware"},"reason":"need it"}'
st = C.new_state()
e = C.tick(L, st, now, perceive_fn=lambda L, n: dict(P), camera_fn=lambda L, s, n: [])
check("request_account tick records its own cap only",
      e["result"] == "ok" and e["choice"]["action"] == "request_account"
      and [a for t, a in st["recent"] if a == "request_account"] == ["request_account"]
      and [a for t, a in st["recent"] if a == "message_zack"] == []
      and len(sent) == before + 1, (e.get("result"), st["recent"], len(sent)-before))
check("persona mentions the address but outbound tick journal does not",
      C.ACCOUNT_EMAIL in C.persona() and C.ACCOUNT_EMAIL not in json.dumps(e)
      and "private until Zack" in C.persona())
check("manifest says it only asks and must not share the email",
      "only ASKS" in manifest(C.new_state()) and "must not share" in manifest(C.new_state())
      and "Nova creates" in manifest(C.new_state()), manifest(C.new_state()))

# CLI: list and resolve
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests"])
out = buf.getvalue()
check("cli requests lists pending", rc == 0 and "pinos.world" in out and "pending" in out and "github.com" in out, out)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests", "resolve", "1", "approved"])
check("cli resolve 1 approved", rc == 0 and "approved" in buf.getvalue() and C.load_account_requests()[0]["status"] == "approved", buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests", "resolve", "1", "denied"])
check("cli will not re-resolve", rc == 1 and "already approved" in buf.getvalue(), buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests", "resolve", "99", "denied"])
check("cli resolve missing id fails", rc == 1 and "no request 99" in buf.getvalue(), buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests", "resolve", "2", "nope"])
check("cli resolve bad status fails", rc == 2, buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.cli(["requests", "resolve", "2", "denied"])
check("cli resolve 2 denied", rc == 0 and C.load_account_requests()[1]["status"] == "denied", buf.getvalue())
# grokbot-cypher wrapper forwards to cypherd
cli = os.path.join(SRC, "grokbot-cypher")
pr = __import__("subprocess").run([cli, "requests"], capture_output=True, text=True, env=dict(os.environ, CYPHER_DAEMON=os.path.join(SRC, "cypherd.py"), CYPHER_NO_SYSTEMCTL="1"))
check("grokbot-cypher requests lists them", pr.returncode == 0 and "github.com" in pr.stdout, pr.stdout + pr.stderr)
C._http = real_http

# ---- house controls stay impossible; Alpha keeps deck-only actions off ----
check("no phase-3 action name is a house control", not any(C.HOUSE_WORDS.search(a) for a in L["actions"]))
A = load("alpha", host="alpha"); LA = A.current_limits(A.new_state())
check("Alpha standby: no phone, glance, note or color", not any(a in A.allowed_actions(LA) for a in A.DECK_ONLY))
check("Alpha standby: look_up allowed", "look_up" in A.allowed_actions(LA))
J = "".join(open(os.path.join(T, "data", "journal", f)).read() for f in os.listdir(os.path.join(T, "data", "journal")))
check("journal never contains the token or topic", TOKEN not in J and TOPIC not in J)
J = "".join(open(os.path.join(T, "data", "journal", f)).read() for f in os.listdir(os.path.join(T, "data", "journal")))
Rf = open(C.requests_file()).read() if os.path.exists(C.requests_file()) else ""
check("journal and request file never contain the email or topic", C.ACCOUNT_EMAIL not in J and C.ACCOUNT_EMAIL not in Rf and TOPIC not in J and TOPIC not in Rf)
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
