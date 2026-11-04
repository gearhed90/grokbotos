#!/usr/bin/env python3
"""Onshape pad: cadpad.py client (config, token, signing, table) against the real
onshape-pad-helper (tools/onshape-pad) with a mock xdotool. No display or network."""
import json, os, re, shutil, socket, stat, subprocess, sys, tempfile, time, importlib.util, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
NOVA = os.path.join(REPO, "build_files", "rpi5", "nova"); HELPER = os.path.join(REPO, "tools", "onshape-pad", "onshape-pad-helper")
sys.path.insert(0, NOVA)
import cadpad as P
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))

T = tempfile.mkdtemp(); X = os.path.join(T, "xdo"); os.makedirs(X); CFG = os.path.join(T, "cfg"); os.makedirs(CFG)
xdo = os.path.join(T, "xdotool"); shutil.copy(os.path.join(HERE, "mock_xdotool.py"), xdo); os.chmod(xdo, 0o755)

# --- the button table ---
import importlib.machinery
_ld = importlib.machinery.SourceFileLoader("pad_helper", HELPER); H = importlib.util.module_from_spec(importlib.util.spec_from_loader("pad_helper", _ld)); _ld.exec_module(H)
used = {n for _, names in P.PAGES for n in names} | set(P.COMMON)
check("every pad button is a known action", used <= set(P.ACTIONS), used - set(P.ACTIONS))
check("every action is on a page", set(P.ACTIONS) <= used, set(P.ACTIONS) - used)
bad = [n for n, (_, s) in P.ACTIONS.items() if not isinstance(s, dict) and not all(H.KEY_RE.match(k) for k in s)]
check("all keys pass the helper's key filter", not bad, bad)
check("search names pass the helper's filter", all(H.NAME_RE.match(s["search"]) for _, s in P.ACTIONS.values() if isinstance(s, dict)))
check("page names", [t for t, _ in P.PAGES] == ["Sketch", "Part Studio", "Assembly", "View"])
D = dict((n, s) for n, (_, s) in P.ACTIONS.items())
check("Onshape defaults", D["sketch"] == ["shift+s"] and D["extrude"] == ["shift+e"] and D["fillet"] == ["shift+f"]
      and D["line"] == ["l"] and D["mate"] == ["m"] and D["insert"] == ["i"] and D["view_iso"] == ["shift+7"]
      and D["revolve"] == ["shift+w"] and D["trim"] == ["m"] and D["offset"] == ["o"] and D["measure"] == ["bracketleft"])
check("no-default tools use search", D["chamfer"] == {"search": "Chamfer"} and D["hole"] == {"search": "Hole"})
out = subprocess.run([sys.executable, os.path.join(NOVA, "cadpad.py"), "--dump-actions"], capture_output=True, text=True)
dump = json.loads(out.stdout)
open(os.path.join(CFG, "actions.json"), "w").write(out.stdout)
H.CFG_DIR = CFG
check("--dump-actions works without GTK and loads in the helper", len(dump["actions"]) == len(P.ACTIONS) == len(H.load_actions()))

# --- config ---
c1 = os.path.join(T, "sys.conf"); c2 = os.path.join(T, "user.conf")
check("defaults without config", P.read_conf([os.path.join(T, "none")]) == {"HOST": "192.168.12.126", "PORT": "8790"})
open(c1, "w").write("# x\nHOST=192.168.12.126\nPORT=8790\n"); open(c2, "w").write('HOST="10.0.0.5"\nPORT=99999\nEVIL=$(rm -rf /)\n')
check("user config overrides host; bad port ignored", P.read_conf([c1, c2]) == {"HOST": "10.0.0.5", "PORT": "8790"})
open(c2, "w").write("HOST=a b;c\n")
check("bad host line ignored", P.read_conf([c1, c2])["HOST"] == "192.168.12.126")

# --- token ---
tok = os.path.join(T, "cadpad.token")
try: P.read_token(tok); r = None
except P.PadError as e: r = str(e)
check("missing token", r == "no token", r)
TOKEN = "ab" * 32
open(tok, "w").write(TOKEN + "\n"); os.chmod(tok, 0o644)
try: P.read_token(tok); r = None
except P.PadError as e: r = str(e)
check("world-readable token refused", r == "token file must be 0600", r)
os.chmod(tok, 0o600)
check("0600 token read", P.read_token(tok) == TOKEN.encode())
shutil.copy(tok, os.path.join(CFG, "token")); os.chmod(os.path.join(CFG, "token"), 0o600)
h1 = P.sign(b"k", "GET", "/health", b"", ts=1000, nonce="nonce1234")
check("signature format", h1["X-Pad-Time"] == "1000" and re.match(r"^[0-9a-f]{64}$", h1["X-Pad-Sig"]) and
      h1 != P.sign(b"k", "GET", "/health", b"x", ts=1000, nonce="nonce1234"))
ht = os.path.join(T, "home"); os.makedirs(ht)
r = subprocess.run(["bash", os.path.join(NOVA, "grokbot-cadpad-token")], input=TOKEN + "\n", capture_output=True, text=True, env=dict(os.environ, HOME=ht))
saved = os.path.join(ht, ".config/grokbot/cadpad.token")
check("grokbot-cadpad-token saves 0600 and prints no token", r.returncode == 0 and open(saved).read().strip() == TOKEN
      and stat.S_IMODE(os.stat(saved).st_mode) == 0o600 and TOKEN not in r.stdout + r.stderr, r.stderr)
r = subprocess.run(["bash", os.path.join(NOVA, "grokbot-cadpad-token")], input="nope\n", capture_output=True, text=True, env=dict(os.environ, HOME=ht))
check("grokbot-cadpad-token rejects junk", r.returncode != 0)

# --- against the helper (real code, mock xdotool) ---
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
LOG = os.path.join(T, "helper.log")
env = dict(os.environ, PAD_CFG_DIR=CFG, PAD_LOG=LOG, PAD_PORT=str(PORT), PAD_BIND="127.0.0.1",
           PAD_ALLOW_NET="127.0.0.0/8", PAD_XDOTOOL=xdo, MOCK_XDO_DIR=X)
hp = subprocess.Popen([sys.executable, HELPER], env=env, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: socket.create_connection(("127.0.0.1", PORT), .2).close(); break
        except OSError: time.sleep(.1)
    cl = P.Client(conf={"HOST": "127.0.0.1", "PORT": str(PORT)}, token_path=tok)
    keys = lambda: open(os.path.join(X, "keys.log")).read().splitlines() if os.path.exists(os.path.join(X, "keys.log")) else []
    h = cl.health(); check("health: helper up, Onshape closed", h.get("ok") and h.get("onshape_open") is False, h)
    check("status yellow when Onshape closed", P.status_of(h)[0] == "yellow")
    r = cl.press("extrude"); check("press refused when Onshape not open", r.get("error") == "onshape not open" and not keys(), (r, keys()))
    open(os.path.join(X, "open"), "w").close()
    check("status green when Onshape open", P.status_of(cl.health())[0] == "green")
    r = cl.press("extrude"); check("press focuses Onshape then sends shift+e", r.get("ok") and keys() == ["111 key shift+e"], (r, keys()))
    r = cl.press("chamfer"); k = keys()[1:]
    check("no-default tool: Alt+C, type name, Enter", r.get("ok") and k == ["111 key alt+c", "111 type Chamfer", "111 key Return"], (r, k))
    open(os.path.join(X, "active"), "w").write("222"); open(os.path.join(X, "nofocus"), "w").close(); n = len(keys())
    r = cl.press("line"); check("no keys when focus can't be taken", r.get("error") == "could not focus onshape" and len(keys()) == n, (r, keys()))
    check("no key ever went to another window", all(l.startswith("111 ") for l in keys()), keys())
    os.remove(os.path.join(X, "nofocus"))
    r = cl.press("bogus"); check("client refuses unknown action", r.get("error") == "unknown action")
    def raw(method, path, body=b"", hdr=None):
        rq = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=body if method == "POST" else None, headers=hdr or {}, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=3) as x: return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
    check("unsigned 401", raw("GET", "/health")[0] == 401)
    hd = P.sign(TOKEN.encode(), "GET", "/health", b""); a = raw("GET", "/health", hdr=hd); b = raw("GET", "/health", hdr=hd)
    check("replay refused", a[0] == 200 and b[1].get("error") == "replay", (a, b))
    check("stale refused", raw("GET", "/health", hdr=P.sign(TOKEN.encode(), "GET", "/health", b"", ts=time.time() - 90))[1].get("error") == "stale")
    check("wrong token refused", raw("GET", "/health", hdr=P.sign(b"cd" * 32, "GET", "/health", b""))[1].get("error") == "badsig")
    body = json.dumps({"keys": "ctrl+alt+t"}).encode(); n = len(keys())
    st, j = raw("POST", "/press", body, P.sign(TOKEN.encode(), "POST", "/press", body))
    check("raw keys never accepted", st == 409 and len(keys()) == n, (st, j))
    os.chmod(tok, 0o644); r = cl.health(); os.chmod(tok, 0o600)
    check("client won't use a loose token", r.get("error") == "token file must be 0600" and P.status_of(r)[0] == "red", r)
    cl2 = P.Client(conf={"HOST": "127.0.0.1", "PORT": "1"}, token_path=tok, timeout=1)
    check("unreachable -> red", P.status_of(cl2.health()) == ("red", "Can't reach Alpha"))
    lg = open(LOG).read()
    check("helper log has action names, no token or signature", "press extrude -> ok" in lg and TOKEN not in lg and "X-Pad" not in lg, lg[-300:])
finally:
    hp.terminate(); hp.wait(5)
# helper refuses a loose token file at start
os.chmod(os.path.join(CFG, "token"), 0o644)
r = subprocess.run([sys.executable, HELPER], env=env, capture_output=True, text=True, timeout=10)
check("helper won't start with a non-0600 token", r.returncode != 0 and "0600" in r.stderr, r.stderr)

# --- novad wiring ---
os.environ["NOVA_SYS_KEY_FILE"] = ""; os.environ["NOVA_DRY_RUN"] = "1"
os.environ["NOVA_SYS_APPS"] = os.path.join(T, "none"); os.environ["NOVA_USER_APPS"] = os.path.join(T, "none")
spec = importlib.util.spec_from_file_location("novad", os.path.join(NOVA, "novad.py")); novad = importlib.util.module_from_spec(spec); spec.loader.exec_module(novad)
check("novad lists onshape_pad", novad.installed_apps().get("onshape_pad") == "nova-cadpad")
check("novad open_app onshape_pad", novad.t_open_app("onshape_pad") == {"ok": True, "opened": "onshape_pad"})
src = open(os.path.join(NOVA, "nova_native.py")).read()
check("Nova has the pad corner button", 'name="pad"' in src and "cadpad.py" in src)
shutil.rmtree(T, ignore_errors=True)
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
