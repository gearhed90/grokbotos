#!/usr/bin/env python3
"""cypher-brain-proxy - lets Cypher (the grokbotos Pi 5) think with Alpha's
llama-server without getting in the way of the camera filter. Stdlib only.

llama-server stays on 127.0.0.1:8080. This proxy is the only door to it from
the network, and it is narrow:
  * listens on the LAN and Tailscale addresses only, and only answers clients
    from 192.168.12.0/24, 100.64.0.0/10 (tailnet) or loopback
  * needs a bearer token (~/.config/cypher-proxy/token, mode 0600, never logged)
  * one Cypher request at a time; text-only chat (no images, no tools), prompt
    and answer size capped, upstream timeout
  * cameras go first: it answers 503 busy while llama-server is processing
    anything, for CAMERA_QUIET_S seconds after the eufy gate logs a decision,
    and while the gaming llama-server user unit (llama-server-gaming.service) is active
Phase 2 adds, behind the same network and token checks:
  * POST /lease, GET/POST /sync/state, GET/POST /sync/journal: the mind lease
    and state/journal sync that let a standby cypherd on Alpha take over while
    the deck is unpowered and hand back when it returns (see cypher_sync.py)
  * GET /camera/events?since=SEQ: sanitized camera events written by
    cypher-camfeed (read-only; allowlisted fields only)
Phase 3 adds POST /v1/vision/describe: one JPEG/PNG screenshot of the deck's own
screen (base64, <= MAX_IMAGE_BYTES) described by Qwen3-VL with a fixed prompt
the deck cannot change. Same network, token, one-at-a-time and cameras-first
rules. The image is held in memory for that request only: never written to
disk, logged or forwarded anywhere but llama-server on loopback.
Build 15 adds the library (cypher_library.py, sqlite FTS5): POST /library/add,
POST /library/touch, GET /library/search?q=, GET /library/wander?mode=random|old,
GET /library/stats. Same network and token checks; it never touches llama-server.
Logs one line per request (client, outcome, sizes, latency). Never prompts,
answers, journal text or tokens.
"""
import hmac, ipaddress, json, os, stat, subprocess, sys, threading, time
import urllib.request, urllib.error, urllib.parse
import cypher_sync, cypher_library
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

E = os.environ.get
UPSTREAM = E("CYPHER_PROXY_UPSTREAM", "http://127.0.0.1:8080").rstrip("/")
BINDS = [b.strip() for b in E("CYPHER_PROXY_BIND", "192.168.12.126,100.114.239.111").split(",") if b.strip()]
PORT = int(E("CYPHER_PROXY_PORT", "8090"))
TOKEN_FILE = os.path.expanduser(E("CYPHER_PROXY_TOKEN_FILE", "~/.config/cypher-proxy/token"))
ALLOW_NETS = [ipaddress.ip_network(n.strip()) for n in
              E("CYPHER_PROXY_ALLOW", "192.168.12.0/24,100.64.0.0/10,127.0.0.0/8").split(",") if n.strip()]
CAMERA_LOGS = [os.path.expanduser(p.strip()) for p in
               E("CYPHER_PROXY_CAMERA_LOGS", "~/nova-projects/eufy-filter/decisions.log").split(",") if p.strip()]
CAMERA_QUIET_S = float(E("CYPHER_PROXY_CAMERA_QUIET_S", "30"))
GAMING_CMD = E("CYPHER_PROXY_GAMING_CMD", "systemctl --user is-active --quiet llama-server-gaming.service")
MAX_BODY = 32 * 1024
MAX_PROMPT_CHARS = int(E("CYPHER_PROXY_MAX_PROMPT_CHARS", "6000"))   # about 1,500 tokens
MAX_TOKENS = int(E("CYPHER_PROXY_MAX_TOKENS", "400"))   # build 15: interviews answer in a paragraph; ticks still ask for 150
UPSTREAM_TIMEOUT = float(E("CYPHER_PROXY_TIMEOUT", "20"))
SYNC_ROOT = os.path.expanduser(E("CYPHER_SYNC_DIR", "~/.local/share/cypher-sync"))
LEASE_TTL = float(E("CYPHER_LEASE_TTL", "180"))
CAMFEED_FILE = os.path.expanduser(E("CYPHER_CAMFEED_FILE", "~/.local/share/cypher-camfeed/events.jsonl"))
MAX_SYNC_BODY = 1024 * 1024        # build 15: state carries his mind (beliefs, working memory, lore)
LIBRARY_ROOT = os.path.expanduser(E("CYPHER_LIBRARY_DIR", "~/.local/share/cypher-library"))
MAX_IMAGE_BYTES = int(E("CYPHER_PROXY_MAX_IMAGE_BYTES", str(450 * 1024)))
MAX_VISION_BODY = MAX_IMAGE_BYTES * 4 // 3 + 4096
VISION_TIMEOUT = float(E("CYPHER_PROXY_VISION_TIMEOUT", "60"))
VISION_MAX_TOKENS = int(E("CYPHER_PROXY_VISION_MAX_TOKENS", "90"))
VISION_PROMPT = ("This is a screenshot of a small cyberdeck's own touchscreen. In at most 40 words, say what is on it: "
                 "which apps or windows, and roughly what the person is doing. Do not read out passwords, codes, keys, "
                 "addresses, phone numbers or long text; just name the kind of thing shown.")
store = None   # cypher_sync.Store, made in main() (tests make their own)

one_at_a_time = threading.Lock()
_gaming_cache = [0.0, False]

def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, file=sys.stderr, flush=True)

def read_token():
    """The shared token, only if the file is ours and private (no group/other bits)."""
    try:
        st = os.stat(TOKEN_FILE)
    except OSError:
        return None
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        return None
    with open(TOKEN_FILE) as f:
        t = f.read().strip()
    return t if len(t) >= 32 else None

def client_allowed(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in ALLOW_NETS)

def gaming():
    now = time.monotonic()
    if now - _gaming_cache[0] > 5:
        try:
            _gaming_cache[1] = subprocess.run(GAMING_CMD, shell=True, timeout=5,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        except Exception:
            _gaming_cache[1] = False
        _gaming_cache[0] = now
    return _gaming_cache[1]

def camera_recent():
    now = time.time()
    for p in CAMERA_LOGS:
        try:
            if now - os.stat(p).st_mtime < CAMERA_QUIET_S:
                return True
        except OSError:
            pass
    return False

def upstream_processing():
    """True if llama-server is working on anything (the camera gate or shadow mode),
    None if it does not answer."""
    try:
        with urllib.request.urlopen(UPSTREAM + "/slots", timeout=3) as r:
            slots = json.load(r)
        return any(s.get("is_processing") for s in slots if isinstance(s, dict))
    except Exception:
        return None

def busy_reason():
    if gaming():
        return "gaming"
    if camera_recent():
        return "camera_recent"
    p = upstream_processing()
    if p is None:
        return "upstream_down"
    if p:
        return "camera_busy"
    return None

def clean_messages(msgs):
    """Text-only chat messages; raises ValueError on anything else."""
    if not isinstance(msgs, list) or not 1 <= len(msgs) <= 12:
        raise ValueError("messages")
    out, total = [], 0
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
            raise ValueError("role")
        c = m.get("content")
        if not isinstance(c, str):
            raise ValueError("text only")
        total += len(c)
        out.append({"role": m["role"], "content": c})
    if total > MAX_PROMPT_CHARS:
        raise OverflowError("prompt too long")
    return out

def describe(body):
    """One screenshot -> a short description. Raises ValueError on anything odd."""
    import base64, binascii
    b64 = body.get("image_b64")
    if not isinstance(b64, str) or len(b64) > MAX_VISION_BODY:
        raise ValueError("image")
    try:
        img = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image not base64")
    if len(img) > MAX_IMAGE_BYTES:
        raise OverflowError("image too large")
    if img[:3] == b"\xff\xd8\xff": mime = "image/jpeg"
    elif img[:8] == b"\x89PNG\r\n\x1a\n": mime = "image/png"
    else: raise ValueError("not a jpeg or png")
    try:
        mt = max(1, min(int(body.get("max_tokens") or VISION_MAX_TOKENS), VISION_MAX_TOKENS))
    except (TypeError, ValueError):
        mt = VISION_MAX_TOKENS
    req = {"messages": [{"role": "user", "content": [
               {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, base64.b64encode(img).decode())}},
               {"type": "text", "text": VISION_PROMPT}]}],
           "max_tokens": mt, "temperature": 0.2, "stream": False}
    del img
    r = urllib.request.Request(UPSTREAM + "/v1/chat/completions", data=json.dumps(req).encode(),
                               method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=VISION_TIMEOUT) as resp:
        j = json.load(resp)
    msg = (j.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content") if isinstance(msg.get("content"), str) else ""
    u = j.get("usage") or {}
    return {"model": "qwen3-vl-8b@alpha", "description": " ".join(text.split())[:400],
            "usage": {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}}

def forward(body):
    msgs = clean_messages(body.get("messages"))
    try:
        mt = int(body.get("max_tokens") or MAX_TOKENS)
    except (TypeError, ValueError):
        mt = MAX_TOKENS
    try:
        temp = float(body.get("temperature", 0.7))
    except (TypeError, ValueError):
        temp = 0.7
    req = {"messages": msgs, "max_tokens": max(1, min(mt, MAX_TOKENS)),
           "temperature": max(0.0, min(temp, 1.2)), "stream": False, "cache_prompt": True}
    rf = body.get("response_format")
    if isinstance(rf, dict) and rf.get("type") == "json_object":
        req["response_format"] = {"type": "json_object"}
    r = urllib.request.Request(UPSTREAM + "/v1/chat/completions", data=json.dumps(req).encode(),
                               method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=UPSTREAM_TIMEOUT) as resp:
        j = json.load(resp)
    msg = (j.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content") if isinstance(msg.get("content"), str) else ""
    u = j.get("usage") or {}
    return {"model": "qwen3-vl-8b@alpha",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}}

class H(BaseHTTPRequestHandler):
    server_version = "cypher-brain-proxy"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _gate(self):
        """Network and token checks shared by every endpoint. Returns True if allowed."""
        if not client_allowed(self.client_address[0]):
            self._send(403, {"error": "forbidden"}); return False
        tok = read_token()
        got = self.headers.get("Authorization", "")
        if not tok or not got.startswith("Bearer ") or not hmac.compare_digest(got[7:].strip().encode(), tok.encode()):
            self._send(401, {"error": "unauthorized"}); return False
        return True

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path not in ("/health", "/camera/events", "/sync/state", "/sync/journal", "/library/search", "/library/wander", "/library/stats"):
            return self._send(404, {"error": "not found"})
        if not self._gate():
            return log(self.client_address[0], "GET", u.path, "denied")
        if u.path == "/health":
            return self._send(200, {"ok": True, "busy": busy_reason(), "cypher_in_flight": one_at_a_time.locked()})
        if u.path == "/camera/events":
            try:
                since = int(q.get("since", "0")); limit = max(1, min(int(q.get("limit", "50")), 200))
            except ValueError:
                return self._send(400, {"error": "bad since/limit"})
            return self._send(200, camera_events(since, limit))
        if u.path.startswith("/library/"):
            try:
                lim = int(q.get("limit", "3"))
                if u.path == "/library/search":
                    return self._send(200, {"entries": library.search(q.get("q", "")[:200], lim)})
                if u.path == "/library/wander":
                    return self._send(200, {"entries": library.wander("old" if q.get("mode") == "old" else "random", lim)})
                return self._send(200, library.stats())
            except (ValueError, cypher_library.sqlite3.Error) as e:
                log(self.client_address[0], "library error", type(e).__name__); return self._send(400, {"error": "library"})
        if u.path == "/sync/state":
            return self._send(200, {"lease": store.lease(), "saved": store.get_state()})
        try:
            limit = max(1, min(int(q.get("limit", "500")), 1000))
        except ValueError:
            return self._send(400, {"error": "bad limit"})
        host = q.get("host") if q.get("host") in cypher_sync.HOLDERS else None
        return self._send(200, {"entries": store.get_journal(q.get("since", "")[:40], host, limit)})

    def _body(self, cap):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > cap:
            self._send(413, {"error": "too large"}); return None
        try:
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict): raise ValueError
        except ValueError:
            self._send(400, {"error": "bad json"}); return None
        return body

    def do_POST(self):
        t0 = time.monotonic(); ip = self.client_address[0]
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/v1/chat/completions", "/v1/vision/describe", "/lease", "/sync/state", "/sync/journal", "/library/add", "/library/touch"):
            return self._send(404, {"error": "not found"})
        if not self._gate():
            return log(ip, "POST", path, "denied")
        vision = path == "/v1/vision/describe"
        if path not in ("/v1/chat/completions", "/v1/vision/describe"):
            body = self._body(MAX_SYNC_BODY)
            if body is None:
                return
            try:
                return self._sync_post(ip, path, body)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        body = self._body(MAX_VISION_BODY if vision else MAX_BODY)
        if body is None:
            return log(ip, "rejected body")
        if not one_at_a_time.acquire(blocking=False):
            log(ip, "busy cypher_in_flight"); return self._send(429, {"busy": "cypher_in_flight"})
        try:
            b = busy_reason()
            if b:
                log(ip, "busy", b); return self._send(503, {"busy": b})
            try:
                out = describe(body) if vision else forward(body)
            except OverflowError as e:
                log(ip, "rejected", str(e) or "prompt too long"); return self._send(413, {"error": str(e) or "prompt too long"})
            except ValueError as e:
                log(ip, "rejected", str(e)); return self._send(400, {"error": str(e)})
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log(ip, "upstream error", type(e).__name__); return self._send(503, {"busy": "upstream_error"})
            ms = int((time.monotonic() - t0) * 1000)
            log(ip, "ok vision" if vision else "ok", "%dms" % ms, "in=%s out=%s" % (out["usage"]["prompt_tokens"], out["usage"]["completion_tokens"]))
            out["latency_ms"] = ms
            return self._send(200, out)
        finally:
            one_at_a_time.release()

    def _sync_post(self, ip, path, body):
        holder, epoch = body.get("holder"), body.get("epoch")
        if path == "/lease":
            r = store.lease_op(holder, body.get("op", "renew"), epoch, bool(body.get("handoff")),
                               bool(body.get("deck_unreachable")))
            if r["why"] not in ("primary", "renewed", "status"):
                log(ip, "lease", holder, body.get("op"), r["why"], "epoch", r["epoch"])
            return self._send(200, r)
        if path == "/library/add":
            try:
                n = library.add(body.get("entries"), holder if holder in cypher_sync.HOLDERS else None)
            except cypher_library.sqlite3.Error as e:
                log(ip, "library error", type(e).__name__); return self._send(503, {"error": "library"})
            return self._send(200, {"added": n})
        if path == "/library/touch":
            return self._send(200, {"touched": library.touch(body.get("ids"))})
        if path == "/sync/state":
            ok = store.put_state(holder, epoch, body.get("state"))
            return self._send(200 if ok else 409, {"saved": ok})
        n = store.append_journal(holder, epoch, body.get("entries"))
        return self._send(200, {"added": n})

def camera_events(since, limit):
    """Sanitized events with seq > since (oldest first, at most limit) and the newest seq."""
    evs, last = [], 0
    try:
        with open(CAMFEED_FILE) as f:
            for line in f:
                try: e = json.loads(line)
                except ValueError: continue
                seq = e.get("seq") if isinstance(e.get("seq"), int) else 0
                last = max(last, seq)
                if seq > since:
                    evs.append({k: e.get(k) for k in ("seq", "time", "camera", "kind", "alerted", "source", "id", "names",
                                                       "guess", "reason") if k in e})
    except OSError:
        return {"events": [], "last_seq": 0, "feed": "missing"}
    return {"events": evs[-limit:] if since == 0 else evs[:limit], "last_seq": last, "feed": "ok"}

def serve(addr):
    """Bind addr:PORT, retrying while the address does not exist yet (Tailscale still starting)."""
    while True:
        try:
            srv = ThreadingHTTPServer((addr, PORT), H)
            srv.daemon_threads = True
            log("listening on %s:%d" % (addr, PORT))
            srv.serve_forever()
        except OSError as e:
            log("cannot bind %s:%d (%s), retrying in 30 s" % (addr, PORT, e.strerror or type(e).__name__))
            time.sleep(30)

def main():
    if read_token() is None:
        log("no usable token at %s (needs 0600, owned by us, 32+ chars); not starting" % TOKEN_FILE)
        sys.exit(78)
    global store, library
    store = cypher_sync.Store(SYNC_ROOT, LEASE_TTL)
    library = cypher_library.Library(LIBRARY_ROOT)
    ts = [threading.Thread(target=serve, args=(a,), daemon=True) for a in BINDS]
    for t in ts: t.start()
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
