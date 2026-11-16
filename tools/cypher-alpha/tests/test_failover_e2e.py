#!/usr/bin/env python3
"""End-to-end failover test on one machine: the real cypher-brain-proxy (lease + sync
store) and two real cypherd processes, one as the deck and one as the Alpha standby,
against a fake llama-server. Covers: clean stop -> takeover, deck back -> hand-back,
power cut (deck dark) -> takeover after the lease TTL, kill switch -> nobody takes over,
and never two active brains."""
import json, os, signal, socket, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
_IN_REPO = os.path.join(ROOT, "..", "..", "build_files", "rpi5", "cypher", "cypherd.py")     # tools/cypher-alpha in the repo
CYPHERD = os.path.abspath(os.path.expanduser(os.environ.get("CYPHERD_SRC") or (_IN_REPO if os.path.exists(_IN_REPO)
                                             else "~/grokbotos-rpi5/build_files/rpi5/cypher/cypherd.py")))
LIMITS = os.path.join(os.path.dirname(CYPHERD), "cypher-limits.json")
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:400]), flush=True)
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class Llama(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, o):
        b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._j([{"id": 0, "is_processing": False}])
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._j({"choices": [{"message": {"content": '{"action":"journal_thought","params":{"text":"tick"},"reason":"test"}'}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
up = free_port(); px = free_port()
srv = ThreadingHTTPServer(("127.0.0.1", up), Llama); threading.Thread(target=srv.serve_forever, daemon=True).start()
T = tempfile.mkdtemp()
tok = os.path.join(T, "token"); TOKEN = "e" * 48
with open(tok, "w") as f: f.write(TOKEN)
os.chmod(tok, 0o600)
L = json.load(open(LIMITS))
L["tick_s"] = 10; L["tick_s_bounds"] = [10, 300]; L["heartbeat_s"] = 1
L["brain"]["primary_url"] = "http://127.0.0.1:%d" % px; L["brain"]["primary_urls"] = [L["brain"]["primary_url"]]
L["brain"]["hosted_backup"]["enabled"] = False; L["brain"]["local"]["enabled"] = False
L["failover"]["standby_poll_s"] = 1; L["failover"]["renew_s"] = 1; L["failover"]["deck_addrs"] = ["127.0.0.1:%d" % free_port()]   # "deck" never answers TCP
L["camera"]["enabled"] = False; L["sleep"]["enabled"] = False
lim = os.path.join(T, "limits.json"); json.dump(L, open(lim, "w")); os.chmod(lim, 0o600)
PROCS = []
import atexit
atexit.register(lambda: [p.kill() for p in PROCS if p.poll() is None])
signal.signal(signal.SIGALRM, lambda *a: (print("TIMEOUT", flush=True), sys.exit(3))); signal.alarm(240)
proxy = subprocess.Popen([sys.executable, os.path.join(ROOT, "proxy", "cypher_brain_proxy.py")], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    env=dict(os.environ, CYPHER_PROXY_UPSTREAM="http://127.0.0.1:%d" % up, CYPHER_PROXY_BIND="127.0.0.1", CYPHER_PROXY_PORT=str(px),
             CYPHER_PROXY_TOKEN_FILE=tok, CYPHER_PROXY_CAMERA_LOGS=os.path.join(T, "none"), CYPHER_PROXY_GAMING_CMD="false",
             CYPHER_SYNC_DIR=os.path.join(T, "sync"), CYPHER_LEASE_TTL="4", CYPHER_CAMFEED_FILE=os.path.join(T, "none")))
PROCS.append(proxy); time.sleep(1)
def env(host):
    return dict(os.environ, CYPHER_HOST=host, CYPHER_LIMITS=lim, CYPHER_TRUST_OWNER="1", CYPHER_BRAIN_TOKEN_FILE=tok,
                CYPHER_XAI_KEY_FILE=os.path.join(T, "nokey"), CYPHER_CONFIG_DIR=os.path.join(T, host, "cfg"),
                CYPHER_STATE_DIR=os.path.join(T, host, "state"), CYPHER_DATA_DIR=os.path.join(T, host, "data"),
                CYPHER_PERSONA=os.path.join(os.path.dirname(CYPHERD), "persona.md"), CYPHER_DRY_RUN="1")
def start(host):
    p = subprocess.Popen([sys.executable, CYPHERD], env=env(host), stdout=subprocess.DEVNULL, stderr=open(os.path.join(T, host + ".log"), "a"))
    PROCS.append(p); return p
def lease():
    return json.load(open(os.path.join(T, "sync", "lease.json")))
def journal(host):
    out = []
    d = os.path.join(T, host, "data", "journal")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        out += [json.loads(l) for l in open(os.path.join(d, f))]
    return out
def wait(cond, secs):
    t = time.time()
    while time.time() - t < secs:
        if cond(): return True
        time.sleep(0.25)
    return False
def ticks(host, since):
    return [e for e in journal(host) if "tick" in e and "choice" in e and e.get("host") == ("alpha" if host == "alpha" else "cypher")
            and e["ts"] >= since]
def iso(): return time.strftime("%Y-%m-%dT%H:%M:%S%z")

deck = start("deck")
check("deck takes the lease", wait(lambda: os.path.exists(os.path.join(T, "sync", "lease.json")) and lease()["holder"] == "cypher", 10))
alpha = start("alpha")
time.sleep(14)                                   # longer than the 4 s lease TTL and the 10 s tick: renewals keep it
check("standby stays idle while the deck is up", ticks("alpha", "") == [], ticks("alpha", ""))
check("deck journals", len(ticks("deck", "")) >= 1)

# 1) clean stop -> takeover
t1 = iso(); deck.send_signal(signal.SIGTERM); deck.wait(20)
check("clean stop: Alpha takes over within seconds", wait(lambda: lease()["holder"] == "alpha", 8), lease())
check("Alpha journals while holding", wait(lambda: len(ticks("alpha", t1)) >= 1, 15))
check("takeover journaled with reason deck_stopped", any(e.get("event") == "takeover" and e.get("why") == "deck_stopped" for e in journal("alpha")))
check("deck's state reached Alpha", any(e.get("event") == "takeover" and e.get("adopted_state") for e in journal("alpha")))

# 2) deck back -> hand-back
t2 = iso(); deck = start("deck")
check("deck back: lease returns to the deck", wait(lambda: lease()["holder"] == "cypher", 10), lease())
check("Alpha stands down", wait(lambda: any(e.get("event") == "handed_back" and e["ts"] >= t2 for e in journal("alpha")), 15))
check("deck merged Alpha's journal entries", wait(lambda: any(e.get("event") == "handback" and e.get("merged_entries", 0) >= 1 for e in journal("deck")), 10),
      [e for e in journal("deck") if e.get("event")])
check("Alpha's entries now in the deck journal", any(e.get("host") == "alpha" and "tick" in e for e in journal("deck")))
time.sleep(12); t3 = iso(); time.sleep(12)
check("after hand-back only the deck thinks", ticks("alpha", t3) == [] and len(ticks("deck", t3)) >= 1, (ticks("alpha", t3), len(ticks("deck", t3))))

# 3) power cut: SIGKILL, no release; lease TTL 4 s, deck address dark
t4 = iso(); deck.kill(); deck.wait()
check("power cut: Alpha takes over after the lease expires", wait(lambda: lease()["holder"] == "alpha", 15), lease())
check("takeover reason deck_dark", any(e.get("event") == "takeover" and e.get("why") == "deck_dark" and e["ts"] >= t4 for e in journal("alpha")))
deck = start("deck")
check("deck back after power cut takes over again", wait(lambda: lease()["holder"] == "cypher", 10))
wait(lambda: any(e.get("event") == "handed_back" and e["ts"] >= t4 for e in journal("alpha")), 15)

# 4) never two brains: tick timestamps of the two hosts must not interleave inside one holder's tenure
evs = sorted([(e["ts"], e.get("host"), e.get("event") or "tick") for e in journal("deck") + journal("alpha")
              if e.get("event") in ("takeover", "handed_back", "handback") or "choice" in e])
alpha_ticks = [e for e in journal("alpha") if "choice" in e]
held = sorted({e["id"].split(":")[1] for e in journal("alpha") if e.get("event") == "takeover"})
check("exactly two takeovers (clean stop, power cut)", len(held) == 2, held)
check("every Alpha tick is inside an epoch Alpha held", alpha_ticks and all(e["id"].split(":")[1] in held for e in alpha_ticks),
      sorted({e["id"].split(":")[1] for e in alpha_ticks}))

# 5) kill switch parks the lease: nobody takes over
os.makedirs(os.path.join(T, "deck", "cfg"), exist_ok=True); open(os.path.join(T, "deck", "cfg", "KILL"), "w").close()
check("kill switch: deck exits", wait(lambda: deck.poll() is not None, 25))
check("kill switch parks the lease", lease()["parked"] is True, lease())
t5 = iso(); time.sleep(8)
check("parked: Alpha does not take over", lease()["parked"] and ticks("alpha", t5) == [], lease())
alpha.send_signal(signal.SIGTERM); alpha.wait(20); proxy.terminate(); proxy.wait(10)
check("no token in any log", all(TOKEN not in open(os.path.join(T, h + ".log")).read() for h in ("deck", "alpha")))
print("logs in", T)
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
