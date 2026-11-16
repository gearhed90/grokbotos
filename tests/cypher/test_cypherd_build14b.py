#!/usr/bin/env python3
"""Build 14b: read-only web browsing (browse: SearXNG, then pages and on-topic links; GET only through a pinned
IP, no cookies, logins, forms or checkouts; refusing sites fall back to the snippet, then the Internet Archive,
then the next result), a browser User-Agent for page reads, the terminal app, and no no-op go_to.
No root, network or display: SearXNG, DNS and every page are mocked (one real socket test on 127.0.0.1)."""
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

# ================= 1. browse =================
check("browse is an action with caps 2/hour, 12/day (phase 6)", L0["actions"]["browse"]["per_hour"] == 2 and L0["actions"]["browse"]["per_day"] == 12
      and L0["actions"]["browse"]["phase"] == 6 and "browse" in C.allowed_actions(L))
check("browse ceilings: up to 6/hour, 40/day", C.LIMIT_BOUNDS["browse"] == {"per_hour": (0, 6), "per_day": (0, 40)})
check("browse block shipped (5 pages, 45 s)", L0["browse"]["max_pages"] == 5 and L0["browse"]["session_s"] == 45 and "browse" in C.BLOCKS)
check("browse is free (not a paid search action)", "browse" not in C.DECK_ONLY and "browse" in C.FREE_ACTIVITIES)
st = C.new_state()
v = lambda t, s=None, n=now: C.validate(L, s or st, P, {"action": "browse", "params": {"topic": t}}, n)
check("browse ok for a subject", v("cyberpunk architecture")[:2] == ("browse", {"topic": "cyberpunk architecture"}))
for bad in ("buy a 3d printer", "order a pizza online", "log in to github", "sign up for Prusa", "add to cart Bambu X1",
            "checkout my cart", "https://shop.example/cart", "x" * 81, "", "my password"):
    check("browse refused: %r" % bad, v(bad)[0] == "none", v(bad))
check("browse: 'order' as a word in a subject is fine", v("Order of the Phoenix")[0] == "browse")
check("browse in the prompt manifest (read-only, no buying)", "browse - FREE read-only web browsing" in C.MANIFEST_TEXT["browse"]
      and "no buying" in C.MANIFEST_TEXT["browse"] and "browse:" in C.CAN_REACH)
PX["reply"] = '{"action":"none","params":{},"reason":"x"}'; PX["seen"].clear()
C.tick(L, C.new_state(), now, perceive_fn=perceive(P), camera_fn=lambda L, s, n: [])
check("tick prompt lists browse", any("browse - FREE" in m["content"] for b in PX["seen"] for m in b["messages"]), "")
check("chat can queue browse; novad offers the tool", "browse" in C.TALK_ACTIONS
      and 'f("browse"' in open(os.path.join(NOVA, "novad.py")).read()
      and "browse" in open(os.path.join(NOVA, "cypher_link.py")).read().split("QUEUEABLE = ")[1][:200])

# ---- mocked web: DNS, SearXNG and pages ----
DNS = {"en.wikipedia.org": "208.80.154.224", "a.example.org": "93.184.216.10", "b.example.org": "93.184.216.11",
       "c.example.org": "93.184.216.12", "d.example.org": "93.184.216.13", "e.example.org": "93.184.216.14",
       "f.example.org": "93.184.216.15", "web.archive.org": "207.241.224.2", "archive.org": "207.241.224.3",
       "lan.example.org": "192.168.12.50", "rebind.example.org": "93.184.216.99"}
GAI = {"calls": {}}
real_gai = socket.getaddrinfo
def fake_gai(host, port, *a, **k):
    GAI["calls"][host] = GAI["calls"].get(host, 0) + 1
    ip = DNS.get(host, "10.1.1.1")
    if host == "rebind.example.org" and GAI["calls"][host] > 1: ip = "127.0.0.1"       # a rebinding answer
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
socket.getaddrinfo = fake_gai
H = lambda title, body, links="": ("<html><head><title>%s</title><script>x()</script></head><body><nav>menu</nav>%s<p>%s</p></body></html>"
                                    % (title, links, body)).encode()
ONT = "Cyberpunk architecture blends brutalist megastructures, neon signage and dense vertical cities in fiction and design."
PAGES = {
    "https://a.example.org/cyberpunk": (200, "text/html", H("A: Cyberpunk", ONT,
        '<a href="/cyberpunk-architecture-history">cyberpunk architecture history</a> <a href="/cart">cart</a> '
        '<a href="/login?next=/cyberpunk">log in</a> <a href="/checkout">cyberpunk checkout</a> <a href="/gardening">gardens</a> '
        '<a href="mailto:x@y.z">mail</a> <a href="/cyberpunk.pdf">cyberpunk pdf</a> <a href="http://lan.example.org/cyberpunk">lan cyberpunk</a>'),
        [("Set-Cookie", "sid=abc")]),
    "https://a.example.org/cyberpunk-architecture-history": (200, "text/html", H("History", "The history of cyberpunk architecture goes back to Metropolis and Blade Runner sets and Kowloon Walled City photographs."), []),
    "https://c.example.org/x": (403, "text/html", b"Forbidden", []),
    "https://d.example.org/y": (429, "text/html", b"Too many", []),
    "https://e.example.org/z": (200, "text/html", b"<html><title>Just a moment...</title><p>Checking your browser. Enable JavaScript and cookies to continue</p></html>", []),
    "https://f.example.org/w": (200, "text/html", H("F", "Night City in Cyberpunk 2077 has six districts, each with its own architectural style and megabuildings."), []),
    "https://web.archive.org/web/20250101000000/https://d.example.org/y": (200, "text/html", H("D (archived)", "An archived page about cyberpunk architecture: arcologies, skybridges and layered streets in fiction."), []),
}
SNIPS = {"https://a.example.org/cyberpunk": "short",
         "https://c.example.org/x": "C says cyberpunk architecture mixes high tech and decay; a long enough snippet to stand in for the page itself here.",
         "https://d.example.org/y": "", "https://e.example.org/z": "", "https://f.example.org/w": "six districts"}
SEARX = {"results": [{"title": "t", "url": u, "content": s} for u, s in SNIPS.items()]}
REQ = []
def fake_pinned(scheme, host, ip, port, target, headers, timeout, cap):
    REQ.append({"scheme": scheme, "host": host, "ip": ip, "port": port, "target": target, "headers": dict(headers)})
    url = "%s://%s%s" % (scheme, host, target)
    if host == "archive.org" and target.startswith("/wayback/available"):
        if "d.example.org" in target:
            return 200, "application/json", json.dumps({"archived_snapshots": {"closest": {"available": True, "status": "200",
                     "url": "http://web.archive.org/web/20250101000000/https://d.example.org/y"}}}).encode(), None
        return 200, "application/json", b'{"archived_snapshots": {}}', None
    if host == "rebind.example.org":
        return 200, "text/html", H("R", "x" * 80), None
    if url in PAGES:
        code, ct, body, _h = PAGES[url]
        return code, ct, body if code == 200 else b"", None
    return 404, "text/html", b"", None
def fake_get(url, timeout=8, cap=262144, headers=None):
    REQ.append({"searx": url, "headers": dict(headers or {})})
    return 200, "application/json", json.dumps(SEARX).encode(), None
C._pinned_fetch, C._get = fake_pinned, fake_get
LL = json.loads(json.dumps(L))
st = C.new_state()
r = C.do_browse(LL, st, "cyberpunk architecture", now)
pages = [json.loads(l) for l in open(os.path.join(T, "data", "journal", time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl"))
         if '"browse_session"' in l]
pg = pages[-1]["pages"] if pages else []
check("browse: a session reads several pages", r == "ok" and len(pg) == 5, (r, pg))
check("browse: search results first, then on-topic links from the pages read", pg and pg[0]["site"] == "a.example.org"
      and [p["title"] for p in pg].index("History") in (1, 2), pg)
check("browse: at most 2 pages per site", max([p["site"] for p in pg].count(s) for s in {p["site"] for p in pg}) <= 2, pg)
check("browse: a 403 site uses its search snippet", any(p["site"] == "c.example.org" and p["via"] == "snippet" for p in pg), pg)
check("browse: a 429 site with no snippet uses the Internet Archive copy", any(p["site"] == "d.example.org" and p["via"] == "archive" for p in pg), pg)
check("browse: a captcha/challenge page is never fought: skipped for the next result", not any(p["site"] == "e.example.org" for p in pg)
      and any(p["site"] == "f.example.org" for p in pg), pg)
tg = [q.get("target", "") for q in REQ if "target" in q]
check("browse: never fetched cart, login, checkout, mailto, pdf or a LAN link", not any(x in t for t in tg for x in ("/cart", "/login", "/checkout", ".pdf"))
      and not any(q.get("host") == "lan.example.org" for q in REQ), tg)
check("browse: off-topic links not followed", "/gardening" not in tg, tg)
pq = [q for q in REQ if "target" in q]
check("browse: every page request is a GET with a browser User-Agent, no cookies or auth",
      all(q["headers"].get("User-Agent", "").startswith("Mozilla/5.0") for q in pq if q["host"] != "archive.org")
      and all("Cookie" not in q["headers"] and "Authorization" not in q["headers"] for q in pq), pq[:2])
check("browse: the Wayback lookup uses the honest UA", all(q["headers"]["User-Agent"].startswith("grokbotos-cypher") for q in pq if q["host"] == "archive.org"))
check("browse: standard Accept and Accept-Language", all("text/html" in q["headers"].get("Accept", "") or q["host"] == "archive.org" for q in pq)
      and all(q["headers"].get("Accept-Language", "").startswith("en") for q in pq))
check("browse: connects to the IP it checked (pinned)", all(q["ip"] == DNS[q["host"]] for q in pq), [(q["host"], q["ip"]) for q in pq])
check("browse: summaries journaled without links", pg and all("http" not in p["summary"] for p in pg), pg)
f = st["found"][-1][2]
check("browse: what he read reaches the next prompt", f.startswith("read 5 pages: ") and "http" not in f, f)
check("browse: SearXNG called with the deck's IP headers", any("X-Forwarded-For" in q["headers"] for q in REQ if "searx" in q))
# nothing readable anywhere
SEARX_SAVE = SEARX["results"]; SEARX["results"] = [{"title": "t", "url": "https://e.example.org/z", "content": ""}]
C.save_lessons([]); st2 = C.new_state()
r = C.do_browse(LL, st2, "zzqx nonsense", now)
check("browse: nothing readable is 'not found' and a lesson", r == "not found" and any(x["key"] == "browse_empty" for x in C.load_lessons()), r)
check("browse: that topic is on a cooldown", "came up empty" in C.validate(LL, st2, P, {"action": "browse", "params": {"topic": "zzqx nonsense"}}, now + 60)[2]
      and C.validate(LL, st2, P, {"action": "browse", "params": {"topic": "zzqx nonsense"}}, now + 6 * 3600 + 5)[0] == "browse")
SEARX["results"] = SEARX_SAVE
def down(*a, **k): raise OSError("down")
C._get = down; real_http = C._http; C._http = down
check("browse: SearXNG and Wikipedia both down is a failure, not a lesson", C.do_browse(LL, C.new_state(), "arcology", now) == "browse failed: search unreachable")
C._http = real_http; C._get = fake_get
# safety primitives
check("pinned: a rebinding name connects to the first (public) answer only", C.safe_get("https://rebind.example.org/a") is not None
      and [q["ip"] for q in REQ if q.get("host") == "rebind.example.org"][-1] == "93.184.216.99")
for u, want in (("https://a.example.org/cyberpunk", True), ("http://lan.example.org/x", False), ("https://10.0.0.1/x", False),
                ("https://u:p@a.example.org/", False), ("https://a.example.org/?token=1", False), ("https://intranet.local/x", False),
                ("https://a.example.org:8443/x", False), ("ftp://a.example.org/x", False)):
    check("public_ip %s -> %s" % (u, want), (C.public_ip(u) is not None) == want)
for u, want in (("https://a.example.org/wiki/Arcology", True), ("https://shop.example.org/cart", False), ("https://x.example.org/checkout/step1", False),
                ("https://x.example.org/account/login", False), ("https://x.example.org/signup", False), ("https://x.example.org/p?add-to-cart=12", False),
                ("https://x.example.org/file.pdf", False), ("https://x.example.org/blog/post/12", True)):
    check("read_only_url %s -> %s" % (u, want), C.read_only_url(u) == want)
n0 = len(REQ)
check("safe_get never fetches a disallowed URL", C.safe_get("https://shop.example.org/checkout") is None and C.safe_get("http://lan.example.org/") is None and len(REQ) == n0)
C.safe_get("https://f.example.org/w", headers={"Cookie": "a=b", "Authorization": "x"})
check("safe_get strips Cookie and Authorization whatever is passed", "Cookie" not in REQ[-1]["headers"] and "Authorization" not in REQ[-1]["headers"], REQ[-1])
check("refused(): 403, 429 and challenge pages; a normal page is fine", C.refused(403) and C.refused(429) and C.refused(200, b"<title>Just a moment...</title>")
      and not C.refused(200, H("ok", ONT)) and not C.refused(404))
src = open(os.path.join(SRC, "cypherd.py")).read()
seg = src[src.index("def _pinned_fetch"):src.index("# GET-only browsing still skips links")]
check("the page fetcher only ever sends GET", 'c.request("GET", target, headers=headers)' in seg and '"POST"' not in seg and "data=" not in seg)
bseg = src[src.index("# ---------- build 14b: browse"):src.index("# ---------- build 12: web search")]
check("browse code has no POST, cookie jar, form submit or credentials", not any(x in bseg for x in ('"POST"', "CookieJar", "cookiejar", "read_secret", ".submit(", "data=")))
# look_up's page read gets the same fallbacks
st3 = C.new_state()
check("look_up page read: a refusing site falls back to the archive", C.read_page(L["lookup"], "https://d.example.org/y") .startswith("An archived page"))
check("look_up page read: a challenge page with no archive is skipped", C.read_page(L["lookup"], "https://e.example.org/z") is None)
socket.getaddrinfo = real_gai
# a real pinned connection on loopback: Host header is the name, the socket goes to the pinned IP, method GET
SEEN = {}
class Web(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN.update(method="GET", host=self.headers.get("Host"), cookie=self.headers.get("Cookie"), path=self.path)
        b = b"<p>hello pinned world</p>"; self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "sid=1"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self): SEEN.update(method="POST"); self.send_response(405); self.end_headers()
wp = free_port(); ws = ThreadingHTTPServer(("127.0.0.1", wp), Web); threading.Thread(target=ws.serve_forever, daemon=True).start()
import importlib
real_pf = importlib.util.spec_from_file_location("pf", os.path.join(SRC, "cypherd.py"))
C2 = load(os.path.join(SRC, "cypherd.py"), "cypherd_b14b_pf", CYPHER_HOST="deck")
code, ct, body, loc = C2._pinned_fetch("http", "example.test", "127.0.0.1", wp, "/page?q=1", {"Host": "example.test", "User-Agent": C2.BROWSER_UA}, 5, 4096)
check("real socket: pinned to the IP, Host is the name, GET, no cookie sent", code == 200 and body == b"<p>hello pinned world</p>"
      and SEEN == {"method": "GET", "host": "example.test", "cookie": None, "path": "/page?q=1"}, SEEN)
code, *_ = C2._pinned_fetch("http", "example.test", "127.0.0.1", wp, "/again", {"Host": "example.test"}, 5, 4096)
check("real socket: a Set-Cookie is never sent back", SEEN["cookie"] is None and SEEN["path"] == "/again")
ws.shutdown()

# ================= 2. the terminal app =================
N = load(os.path.join(NOVA, "novad.py"), "novad_b14b")
apps = N.installed_apps()
check("terminal is an allowed app (grokbot-term, foot)", apps.get("terminal") == "grokbot-term")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    r1 = N.t_open_app("terminal"); r2 = N.t_open_app("foot")
check("open_app terminal (and 'foot') launches grokbot-term", r1 == {"ok": True, "opened": "terminal"} and r2 == {"ok": True, "opened": "terminal"}
      and err.getvalue().count('DRY-RUN launch: ["/usr/local/bin/grokbot-term"]') == 2, err.getvalue())
sch = [t["function"] for t in N.tool_schema() if t["function"]["name"] == "open_app"][0]
check("open_app tool lists terminal", "terminal" in sch["parameters"]["properties"]["name"]["enum"] and "terminal" in sch["description"])
check("the chat facts say there is a terminal", "there IS a terminal" in N.TOOL_RULES
      and "terminal on your screen" in open(os.path.join(NOVA, "cypher_link.py")).read())
check("other apps are still refused", N.t_open_app("bash")["ok"] is False)

# ================= 3. go_to never offers where he is =================
st = C.new_state(); st["place"] = "noodle_stall"; PX["seen"].clear()
C.tick(L, st, now + 7200, perceive_fn=perceive(P), camera_fn=lambda L, s, n: [])
prompt = "\n".join(m["content"] for b in PX["seen"] for m in b["messages"])
gl = [l for l in prompt.splitlines() if l.startswith("- go_to")]
check("go_to's options leave out where he is", gl and "noodle_stall" not in gl[0].split("one of", 1)[1] and "you are at noodle_stall now" in gl[0], gl)
wl = [l for l in C.world_lines(L, st, P, C.allowed_actions(L), now).splitlines() if l.startswith("world (your manifest)")]
check("the world line lists other places only", wl and "other places: apartment." in wl[0], wl)
v = C.validate(L, st, P, {"action": "go_to", "params": {"place": "noodle_stall"}}, now)
check("a go_to to where he is is refused, pointing at eat", v[0] == "none" and "already at noodle_stall" in v[2] and "choose eat" in v[2], v)
st["place"] = None
check("an unset place counts as the apartment", C.validate(L, st, P, {"action": "go_to", "params": {"place": "apartment"}}, now)[0] == "none")
L1 = json.loads(json.dumps(L)); L1["world"]["places"] = {"apartment": "home"}
check("with nowhere else to go, go_to is blocked", (lambda s: (s.update(place="apartment"), C.blocked(L1, s, P, "go_to", now))[1])(C.new_state()) == "nowhere else to go")

# ================= 4. collapsible HUD columns =================
try:
    import cairo; have_cairo = True
except Exception:
    have_cairo = False
if have_cairo:
    CP = load(os.path.join(SRC, "cypher_panels.py"), "cypher_panels_b14b")
    cf = os.path.join(T, "cfg", "panels-collapsed.json")
    check("panels: both columns open by default", CP.collapsed(cf) == {"left": False, "right": False} and CP.COLLAPSED == cf, CP.COLLAPSED)
    open(cf, "w").write("{broken")
    check("panels: a broken state file means open", CP.collapsed(cf) == {"left": False, "right": False})
    CP.set_collapsed("left", True)
    check("panels: state saved (0600) and read back", CP.collapsed() == {"left": True, "right": False} and (os.stat(cf).st_mode & 0o777) == 0o600)
    CP.toggle_collapsed("right"); CP.toggle_collapsed("left")
    check("panels: toggling flips one side", CP.collapsed() == {"left": False, "right": True})
    try: CP.set_collapsed("top", True); check("panels: bad side refused", False)
    except ValueError: check("panels: bad side refused", True)
    W_, H_ = 1280, 720
    both = CP.text_column(W_, H_, True, {"left": False, "right": False})
    one = CP.text_column(W_, H_, True, {"left": True, "right": False})
    none_ = CP.text_column(W_, H_, True, {"left": True, "right": True})
    edge = (CP.MARGIN + CP.COL_W) * H_ / 720.0
    check("panels: open columns keep the 720 px centre column", both[1] <= 720 and both[0] >= edge, both)
    check("panels: one folded column widens the text into its room, not under the other", one[1] > both[1] and one[0] < both[0]
          and one[0] + one[1] <= W_ - edge and one[0] >= CP.STRIP_W, (both, one))
    check("panels: both folded gives the widest column, inside the strips", none_[1] > one[1] and none_[0] >= CP.STRIP_W
          and none_[0] + none_[1] <= W_ - CP.STRIP_W and none_[1] <= int(W_ * .9), none_)
    for side in CP.SIDES:
        for c in (False, True):
            rx, ry, rw, rh = CP.toggle_rect(800, 450, side, {"left": c, "right": c})
            k = 450 / 720.0
            check("panels: %s %s target is finger-sized" % (side, "strip" if c else "tab"), rw >= min(CP.TAB, CP.STRIP_W) * k and rh >= CP.TAB * k)
    colx = {"left": False, "right": False}
    tx, ty, tw, th = CP.toggle_rect(W_, H_, "left", colx)
    check("panels: a tap on the left tab hits left, the middle hits nothing", CP.hit_toggle(W_, H_, tx + 5, ty + 5, colx) == "left"
          and CP.hit_toggle(W_, H_, W_ / 2, H_ / 2, colx) is None)
    check("panels: the corner buttons stay clear of the strips", CP.toggle_rect(W_, H_, "left", {"left": True, "right": True})[1] >= 80)
    check("panels: no journal taps while the right column is folded", not CP.in_journal(W_, H_, 1100, 200, {"left": False, "right": True})
          and CP.in_journal(W_, H_, 1100, 200, {"left": False, "right": False}))
    snap = {"epoch": now, "brain": "ALPHA", "journal": [["2:00", "thought", "hello"]], "lesson_count": 2}
    def px(col):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W_, H_); cr = cairo.Context(s); CP.render_panels(cr, W_, H_, snap, now, col)
        s.flush(); d = s.get_data(); st_ = s.get_stride()
        return lambda x, y: d[y * st_ + x * 4 + 3]                 # alpha
    a_open, a_fold = px({"left": False, "right": False}), px({"left": False, "right": True})
    check("panels: an open right column draws its journal panel", a_open(1100, 200) > 0)
    check("panels: a folded right column leaves only its edge strip", a_fold(1100, 200) == 0 and a_fold(W_ - 5, 400) > 0)
    CP.set_collapsed("left", False); CP.set_collapsed("right", False)
    nn = open(os.path.join(NOVA, "nova_native.py")).read()
    check("Super+[ and Super+] fold the columns", '"bracketleft", "bracketright"' in nn and "toggle_panel" in nn)
else:
    check("no cairo: panel collapse checks skipped", True)
bw = shutil.which("broadwayd")
try:
    import gi; gi.require_version("Gtk", "3.0"); have_gtk = True
except Exception:
    have_gtk = False
if bw and have_gtk and have_cairo:
    disp = ":%d" % (40 + (os.getpid() + 7) % 50)
    bp = subprocess.Popen([bw, disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    probe = os.path.join(T, "probe14b.py")
    open(probe, "w").write(r'''
import json, sys, time, types
sys.path.insert(0, sys.argv[1]); sys.argv = sys.argv[:1]
import nova_native as N
from gi.repository import Gtk, Gdk
a = types.SimpleNamespace(base="http://127.0.0.1:9", offline=True, fullscreen=False, size=(1280, 720), dpr=.5, renderer="cairo",
    state=None, sim=None, blink=None, confirm=None, reply=None, q=None, mic="none", shape=None, color=None, picker=False, ask=None,
    quit_after=None, no_panels=False, journal=False)
def pump(n=40):
    for _ in range(n):
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        time.sleep(0.02)
app = N.Nova(a)
app.say("a long reply " * 30, instant=True); pump(60)
app.hud_key = (False,) + tuple(app.hud_key[1:]); app._watch_hud(); pump(10)
W, H = app.win.get_allocated_width(), app.win.get_allocated_height()
def box(w):
    x, y = w.translate_coordinates(w.get_toplevel(), 0, 0); al = w.get_allocation(); return [x, y, al.width, al.height]
out = {"W": W, "open": box(app.bar), "lines_open": app.reply.get_layout().get_line_count()}
ox, oy = app.win.get_window().get_origin()[1:]
tx, ty, tw, th = N.CP.toggle_rect(W, H, "right")
out["tap"] = app.on_hud_tap(app.win, types.SimpleNamespace(x_root=ox + tx + tw / 2, y_root=oy + ty + th / 2)); pump(40)
out["after_tap"] = N.CP.collapsed(); out["wide"] = box(app.bar)
k = types.SimpleNamespace(keyval=Gdk.keyval_from_name("bracketleft"), state=Gdk.ModifierType.SUPER_MASK)
app.on_key(app.win, k); pump(40)
out["after_key"] = N.CP.collapsed(); out["widest"] = box(app.bar); out["lines_widest"] = app.reply.get_layout().get_line_count()
app.win.hide(); pump(5)
app2 = N.Nova(a); pump(100)
app2.on_size(app2.win, app2.win.get_allocation()); pump(20)
out["restart"] = N.CP.collapsed(); out["restart_bar"] = box(app2.bar)
sx, sy, sw, sh = N.CP.toggle_rect(W, H, "left")
app2.hud_key = (False,) + tuple(app2.hud_key[1:])
out["strip_tap"] = app2.on_hud_tap(app2.win, types.SimpleNamespace(x_root=ox + sx + sw / 2, y_root=oy + sy + sh / 2)); pump(40)
out["after_strip"] = N.CP.collapsed()
print(json.dumps(out))
''')
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=disp, CYPHER_CONFIG_DIR=os.path.join(T, "ui14b-cfg"),
               CYPHER_STATE_DIR=os.path.join(T, "ui14b-state"), NOVA_AVATAR_CFG=os.path.join(T, "ui14b-cfg", "avatar.json"))
    try:
        r = subprocess.run([sys.executable, probe, NOVA], capture_output=True, text=True, env=env, timeout=90)
        g = json.loads(r.stdout.strip().splitlines()[-1])
        check("GTK: a tap on the right tab folds the right column", g["tap"] and g["after_tap"] == {"left": False, "right": True}, g)
        check("GTK: the chat bar widens into the freed space", g["wide"][2] > g["open"][2] and g["wide"][0] + g["wide"][2] > g["open"][0] + g["open"][2], g)
        check("GTK: Super+[ folds the left column; the bar widens again", g["after_key"] == {"left": True, "right": True} and g["widest"][2] > g["wide"][2], g)
        check("GTK: the reply still wraps when wide", 1 < g["lines_widest"] < g["lines_open"], g)
        check("GTK: the folded state survives a restart", g["restart"] == {"left": True, "right": True} and g["restart_bar"][0::2] == g["widest"][0::2], g)
        check("GTK: a tap on the left strip opens the left column", g["strip_tap"] and g["after_strip"] == {"left": False, "right": True}, g)
    except Exception as ex:
        check("GTK probe (panels) ran", False, "%s %s" % (type(ex).__name__, (r.stderr if 'r' in dir() else "")[-600:]))
    finally:
        bp.terminate()
else:
    check("no broadwayd/GTK: panel GTK probe skipped", True)

# Flash of build 14: the deck's older locked file had lookup.hosts = [en.wikipedia.org] only, so SearXNG was off.
_m = C.merge_defaults({"lookup": {"hosts": ["en.wikipedia.org"]}, "actions": {}},
                      {"lookup": {"hosts": ["en.wikipedia.org", "192.168.12.126", "100.114.239.111"],
                                  "searxng_url": "http://192.168.12.126:8888", "searxng_alt_urls": ["http://100.114.239.111:8888"]}})
check("merge: lookup.hosts gains the image's SearXNG hosts", _m["lookup"]["hosts"] == ["en.wikipedia.org", "192.168.12.126", "100.114.239.111"], _m)
check("merge: SearXNG bases come back on an old locked file", C.searxng_bases(_m["lookup"]) == ["http://192.168.12.126:8888", "http://100.114.239.111:8888"], C.searxng_bases(_m["lookup"]))
_m2 = C.merge_defaults({"pino": {"hosts": ["pinos.world"]}}, {"pino": {"hosts": ["pinos.world", "evil.example"]}})
check("merge: other blocks' host lists are not extended", _m2["pino"]["hosts"] == ["pinos.world"], _m2)

srv.shutdown(); shutil.rmtree(T, ignore_errors=True)
print("\nbuild 14b tests: %d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
