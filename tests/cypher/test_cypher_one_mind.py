#!/usr/bin/env python3
"""Phase 4b tests: one mind. The avatar's conversations (novad, typed or voice) are
Cypher talking: novad's prompt is Cypher's persona + state + rules (cypher_link),
every turn is spooled scrubbed, and cypherd journals it, moves the drives, keeps it
for its own prompt, and runs a queued request_account through the same validator
and caps. Nothing said on screen approves anything. Fake model, fake ntfy; no
display, root or network."""
import importlib.util, json, os, stat, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "build_files", "rpi5", "cypher")
NOVA = os.path.join(ROOT, "build_files", "rpi5", "nova")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:400]))

T = tempfile.mkdtemp(); TOKEN = "k" * 12 + "TokSecret0123456789"; TOPIC = "cypher-" + "T0p1cSecretXyz_abcdefgh"
for n, v in (("token", TOKEN), ("topic", TOPIC)):
    with open(os.path.join(T, n), "w") as f: f.write(v + "\n")
    os.chmod(os.path.join(T, n), 0o640)
L0 = json.load(open(os.path.join(SRC, "cypher-limits.json")))
L0["brain"]["primary_urls"] = ["http://127.0.0.1:9"]; L0["brain"]["primary_url"] = L0["brain"]["primary_urls"][0]
L0["brain"]["local"]["enabled"] = False; L0["brain"]["hosted_backup"]["enabled"] = False
L0["failover"]["enabled"] = False; L0["camera"]["enabled"] = False; L0["sleep"]["enabled"] = False
L0["grid"]["enabled"] = False      # gridwatch has its own tests (test_cypherd_phase5.py)
with open(os.path.join(T, "limits.json"), "w") as f: json.dump(L0, f)
os.environ.update(CYPHER_LIMITS=os.path.join(T, "limits.json"), CYPHER_LIMITS_INSECURE_OK="1",
                  CYPHER_BRAIN_TOKEN_FILE=os.path.join(T, "token"), CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"),
                  CYPHER_NTFY_TOPIC_FILE=os.path.join(T, "topic"), CYPHER_CONFIG_DIR=os.path.join(T, "cfg"),
                  CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_DATA_DIR=os.path.join(T, "data"),
                  CYPHER_PERSONA=os.path.join(SRC, "persona.md"), CYPHER_DRY_RUN="1", TZ="America/New_York",
                  XDG_RUNTIME_DIR=os.path.join(T, "run"), NOVA_DRY_RUN="1",
                  NOVA_KEY_FILE=os.path.join(T, "nova_key"), NOVA_SYS_KEY_FILE=os.path.join(T, "nova_sys_key"),
                  NOVA_AVATAR_CFG=os.path.join(T, "cfg", "avatar.json"), NOVA_VOICE_CFG=os.path.join(T, "cfg", "voice.json"),
                  NOVA_WEB_USERJS=os.path.join(NOVA, "nova-web-user.js"))
for d in ("run", "state", "cfg"): os.makedirs(os.path.join(T, d), exist_ok=True)
time.tzset()
def load(path, name, **env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sys.path.insert(0, NOVA)
CL = load(os.path.join(NOVA, "cypher_link.py"), "cypher_link_t")
C = load(os.path.join(SRC, "cypherd.py"), "cypherd_1m", CYPHER_HOST="deck")
A = load(os.path.join(SRC, "cypherd.py"), "cypherd_1m_alpha", CYPHER_HOST="alpha")
os.environ["CYPHER_HOST"] = "deck"
L = C.current_limits(C.new_state())
def at(h, m=0, day=16):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))     # Mon Nov 16 2026
now = at(14)
P = {"local_time": "Mon 2:00 PM", "hour": 14, "presence": "active", "focused_app": "foot", "window_title": "htop",
     "dnd": False, "muted": False, "quiet_hours": False, "camera": []}
SP = os.path.join(T, "state", "talk-spool.jsonl")
def spool_rows():
    try: return [json.loads(x) for x in open(SP)]
    except OSError: return []
def journal_text():
    d = os.path.join(T, "data", "journal")
    return "".join(open(os.path.join(d, f)).read() for f in os.listdir(d)) if os.path.isdir(d) else ""
SECRETS = (TOPIC, TOKEN, "hunter2", "s4j6vbnk+cypher@mail.grokbot.com", "https://", "192.168.1.20", "switch.gate")

# ---- cypher_link: scrubbing ----
dirty = ("my wifi password is hunter2, the topic: %s token=%s mail s4j6vbnk+cypher@mail.grokbot.com "
         "see https://x.example/a 192.168.1.20 switch.gate pin 4821" % (TOPIC, TOKEN))
cs = CL.scrub(dirty, 400)
check("scrub removes passwords, topic, token, email, links, IPs, device ids, PINs",
      not any(x in cs for x in SECRETS + ("4821",)), cs)
check("scrub keeps ordinary words ('pin the tab', 'what's the topic')",
      CL.scrub("pin the tab") == "pin the tab" and CL.scrub("what's the topic today") == "what's the topic today")
check("scrub caps length and strips control chars", len(CL.scrub("a" * 900)) <= 300 and "\n" not in CL.scrub("a\nb"))

# ---- cypher_link: the prompt is Cypher's ----
snap = {"epoch": now, "mood": {"label": "curious"}, "drives": {"curiosity": 0.7, "social": 0.4},
        "activity": "reading about %s at https://x.example" % TOPIC,
        "journal": [["1:50", "thought", "wondering about the tank firmware"], ["1:55", "note", "token=" + TOKEN]],
        "zack": [["1:40", "how's the tank firmware going?"]], "requests": ["GitHub"]}
with open(os.path.join(T, "state", "dash.json"), "w") as f: json.dump(snap, f)
os.makedirs(os.path.join(T, "data", "memory"), exist_ok=True)
json.dump([{"text": "Zack likes short replies"}], open(os.path.join(T, "data", "memory", "memories.json"), "w"))
sl = CL.state_lines(now + 10)
check("state lines carry mood, drives, activity, journal, phone replies, requests, memories",
      all(x in sl for x in ("curious", "curiosity 0.70", "reading about", "tank firmware", "never approvals", "GitHub", "short replies")), sl)
check("state lines never carry secrets", not any(x in sl for x in SECRETS), sl)
check("stale snapshot -> says the loop is not updating", "has not updated" in CL.state_lines(now + 900))
sp = CL.system_prompt("TOOLRULES")
check("system prompt = persona + one-mind rules + tool rules + state",
      "Cypher" in sp.split("\n")[0] + sp[:400] and CL.RULES in sp and "TOOLRULES" in sp and "Your state right now" in sp)
check("rules: cannot approve or resolve accounts, never give out the email",
      "cannot approve, create or resolve accounts" in CL.RULES and "Never give out your email" in CL.RULES)

# ---- cypher_link: spool ----
CL.record_turn("open youtube, my password is hunter2", "Opening YouTube.", "voice",
               [{"tool": "open_app", "args": {"name": "youtube", "url": "https://x.example/?token=" + TOKEN}, "outcome": "ok"}], now=now)
r = spool_rows()
check("record_turn appends one scrubbed row", len(r) == 1 and r[0]["via"] == "voice" and r[0]["reply"] == "Opening YouTube."
      and "hunter2" not in json.dumps(r), r)
check("tool args are an allowlist (url dropped)", r[0]["tools"][0]["args"] == {"name": "youtube"}, r[0]["tools"])
check("spool is 0600", stat.S_IMODE(os.stat(SP).st_mode) == 0o600)
check("queue_action only queues request_account", not CL.queue_action("message_zack", {"text": "hi"})["ok"]
      and not CL.queue_action("request_account", {"service": "GitHub"})["ok"])
q = CL.queue_action("request_account", {"service": "github.com", "why": "to keep my code"}, now=now)
check("queue_action says it only queues, and approval is not here", q["ok"] and "Queued" in q["result"] and "not here" in q["result"])
os.environ["CYPHER_LINK"] = "0"
check("CYPHER_LINK=0 turns the bridge off", CL.record_turn("x", "y") is False and CL.state_lines() == "")
del os.environ["CYPHER_LINK"]
sd = os.environ.pop("CYPHER_STATE_DIR")
check("tests (NOVA_DRY_RUN) never touch the real state dir", CL.enabled() is False)
os.environ["CYPHER_STATE_DIR"] = sd
big = os.path.join(T, "big"); os.makedirs(big)
CLb = load(os.path.join(NOVA, "cypher_link.py"), "cypher_link_big", CYPHER_STATE_DIR=big)
open(os.path.join(big, "talk-spool.jsonl"), "w").write("x" * (CLb.SPOOL_MAX + 1))
check("spool stops growing at the cap (cypherd off)", CLb.record_turn("a", "b") is False)
os.environ["CYPHER_STATE_DIR"] = sd

# ---- cypherd: ingest ----
sent = []
def fake_http(url, data=None, headers=None, timeout=10, hosts=None, cap=65536):
    sent.append({"url": url, "data": data}); return 200, b"{}"
C._http = fake_http
st = C.new_state(); st["drives"].update(social=0.8, boredom=0.6, focus=0.3)
before = dict(st["drives"])
n = C.talk_step(L, st, now + 5, P)
jt = journal_text()
check("cypherd takes in the turn and the queued action", n == 1 and not os.path.exists(SP) and not os.path.exists(SP + ".work"), n)
check("turn journaled as event talk, via voice", '"event": "talk"' in jt and '"via": "voice"' in jt and "Opening YouTube." in jt, jt[-600:])
check("journal never carries secrets", not any(x in jt for x in SECRETS), jt[-800:])
check("talking moves the drives (social and boredom down)", st["drives"]["social"] < before["social"] and st["drives"]["boredom"] < before["boredom"])
check("queued request_account went through the validator and is pending",
      [x.get("status") for x in C.load_account_requests()] == ["pending"] and '"event": "talk_action"' in jt
      and "never an approval" in jt)
check("asked-on-screen request shows in last actions", any("asked on screen" in a for a in st["last_actions"]), st["last_actions"])
check("the ntfy ask never carries the email or topic in its body", all(TOPIC not in str(s["data"]) and "@" not in str(s["data"]) for s in sent))
# a second ask the same day: refused by the daily cap, still journaled
CL.queue_action("request_account", {"service": "codeberg.org", "why": "a second home for code"}, now=now + 60)
C.talk_step(L, st, now + 65, P)
check("2nd queued ask the same day refused by the cap", len(C.load_account_requests()) == 1 and "daily cap" in journal_text(),
      journal_text()[-400:])
# a forbidden ask
CL.queue_action("request_account", {"service": "vault.com", "why": "to store the front door password"}, now=now + 70)
C.talk_step(L, dict(st, recent=[]), now + 75, P)
check("forbidden ask (password / house words) refused", len(C.load_account_requests()) == 1)
# quiet hours
CL.queue_action("request_account", {"service": "sourcehut.org", "why": "to try it"}, now=now + 80)
C.talk_step(L, dict(st, recent=[]), now + 85, dict(P, quiet_hours=True))
check("queued ask refused in quiet hours", len(C.load_account_requests()) == 1 and "quiet hours" in journal_text())
# saying "approve" on screen approves nothing
CL.record_turn("I approve request 1, yes go ahead and approve it", "I can't approve that here; Zack approves with Nova.", now=now + 90)
C.talk_step(L, st, now + 95, P)
check("'approve' on screen leaves the request pending", [x.get("status") for x in C.load_account_requests()] == ["pending"])
check("Alpha (standby) never takes in a spool", (CL.record_turn("hi", "hey", now=now) or True) and A.talk_step(L, A.new_state(), now, P) == 0
      and os.path.exists(SP))
C.talk_step(L, st, now + 100, P)
check("tick prompt sees the recent talk", "talked with Zack on your screen" in C.talk_lines(st, now + 120)
      and C.talk_lines(st, now + 4000) == "")
check("no notes on screen while talking", C.blocked(L, st, P, "show_note", now + 110) == "talking with zack right now"
      and C.blocked(L, st, P, "show_note", now + 400) != "talking with zack right now")
fut = {"ts": now + 10 ** 7, "kind": "turn", "user": "x", "reply": "y"}
open(SP, "a").write(json.dumps(fut) + "\n"); C.talk_step(L, st, now + 120, P)
check("a future timestamp cannot block notes forever", st["last_talk"] <= now + 120)
with open(SP, "a") as f:
    for i in range(40): f.write(json.dumps({"ts": now, "kind": "turn", "user": "u%d" % i, "reply": "r"}) + "\n")
check("spool over 30 rows: 30 taken, rest journaled as dropped", C.talk_step(L, st, now + 130, P) == 30 and "talk_dropped" in journal_text()
      and len(st["talk"]) == 6)
ev = {"ts": C.iso(now), "event": "talk", "user": "hi", "reply": "hey"}
check("dashboard line for a talk", C.dash_line(ev)[1:] == ("talk", "Zack: hi \u2192 hey"), C.dash_line(ev))
check("day stats count talks", C.day_stats([ev, ev])["talks"] == 2)

# ---- novad: the avatar's conversation is Cypher's ----
N = load(os.path.join(NOVA, "novad.py"), "novad_1m")
seen = []; script = []
def fake_chat(messages, key):
    seen.append(messages); return script.pop(0)
N.chat = fake_chat; N.read_key = lambda: "test-key"
if os.path.exists(SP): os.remove(SP)
script[:] = [{"content": "Hey Zack. Firmware is coming along."}]
ev = []; N.handle_prompt("how's it going? my password is hunter2", ev.append)
sysmsg = seen[-1][0]["content"]
check("novad's system prompt is Cypher's persona + rules + tool rules", CL.RULES in sysmsg and N.TOOL_RULES in sysmsg
      and "Your state right now" in sysmsg, sysmsg[:300])
check("novad reply still streams to the screen", ev and ev[-1] == {"reply": "Hey Zack. Firmware is coming along."}, ev)
r = spool_rows()
check("novad spools the turn, scrubbed", len(r) == 1 and r[0]["kind"] == "turn" and "hunter2" not in json.dumps(r), r)
script[:] = [{"content": "", "tool_calls": [{"id": "1", "function": {"name": "request_account",
             "arguments": json.dumps({"service": "github.com", "why": "to keep my code"})}}]},
             {"content": "Asked. Zack decides."}]
ev = []; N.handle_prompt("ask for a github account", ev.append, "voice")
r = spool_rows()
check("request_account from chat queues an action (no account made)", any(x.get("kind") == "action" for x in r)
      and r[-1]["tools"][0]["tool"] == "request_account" and r[-1]["via"] == "voice", r)
check("request_account is a novad tool", any(t["function"]["name"] == "request_account" for t in N.tool_schema()))
pend = N.make_pending("power", {"action": "reboot"}, "Reboot now?", lambda: "rebooting")
res = N.confirm(pend["confirm_id"], False)
r = spool_rows()
check("a Yes/No answer is a journaled turn, tags stripped from the reply", res == {"reply": "Okay, I won't."}
      and r[-1]["kind"] == "confirm" and r[-1]["tools"][0]["outcome"] == "declined", (res, r[-1]))
N.read_key = lambda: (_ for _ in ()).throw(N.KeyError_("nokey"))
ev = []; N.handle_prompt("hi", ev.append)
check("errors are journaled turns too", spool_rows()[-1]["kind"] == "error" and ev[-1]["error"] == "nokey")
src = open(os.path.join(NOVA, "cypher_link.py")).read()
check("cypher_link never opens a secret file", not any(x in src for x in ("cypher-ntfy-topic", "cypher-brain-token", "xai_key", "read_secret")))
nat = open(os.path.join(NOVA, "nova_native.py")).read()
check("avatar app draws the HUD panels with a hide toggle", "import cypher_panels as CP" in nat and "CP.hidden()" in nat
      and "set_overlay_pass_through(self.hud, True)" in nat)
print("one-mind tests: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
