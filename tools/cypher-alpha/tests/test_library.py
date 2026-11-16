#!/usr/bin/env python3
"""Cypher's library on Alpha (build 15): add/dedupe, search, wander, touch, stats, and the proxy endpoints."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "proxy"))
import cypher_library as CL
P = F = 0
def check(name, ok, info=""):
    global P, F
    if ok: P += 1; print("PASS", name)
    else: F += 1; print("FAIL", name, "->", str(info)[:300])
T = tempfile.mkdtemp()
lib = CL.Library(os.path.join(T, "lib"))
check("db is private", oct(os.stat(lib.path).st_mode & 0o777) == "0o600")
rows = [{"id": "m%d" % i, "ts": "2026-11-%02dT10:00:00" % (1 + i), "day": "2026-11-%02d" % (1 + i), "kind": "memory",
         "place": "apartment", "mood": "content", "strength": 1.0, "text": "neon rain over Watson, note %d" % i} for i in range(10)]
rows.append({"id": "c1", "day": "2026-11-15", "kind": "codex", "place": "library", "strength": 2, "text": "Arasaka: a Japanese megacorp of security and banking."})
check("add", lib.add(rows, "cypher") == 11)
check("resend is ignored (by id)", lib.add(rows, "cypher") == 0)
check("junk skipped", lib.add([{"id": "x"}, "bad", {"id": 3, "text": "y"}, {"id": "e", "text": "  "}]) == 0)
try: lib.add("nope"); check("non-list refused", False)
except ValueError: check("non-list refused", True)
s = lib.search("arasaka megacorp")
check("search finds the codex entry", s and s[0]["id"] == "c1" and s[0]["kind"] == "codex", s)
check("search with no words -> nothing", lib.search("!!") == [])
check("search is not SQL/FTS injectable", isinstance(lib.search('" OR 1=1; DROP TABLE shelf; --'), list) and lib.stats()["total"] == 11)
w = lib.wander("random", 2); check("wander random gives 2", len(w) == 2)
o = lib.wander("old", 3); check("wander old prefers old shelves", all(x["day"] <= "2026-11-15" for x in o) and len(o) == 3, o)
lib.touch(["c1"]); s = lib.search("Arasaka")
check("touch strengthens and counts a visit", s[0]["visits"] == 1 and s[0]["strength"] > 2, s)
st = lib.stats(); check("stats", st["total"] == 11 and st["kinds"]["memory"] == 10 and st["oldest"] == "2026-11-01", st)
lib2 = CL.Library(os.path.join(T, "lib")); check("survives reopen", lib2.stats()["total"] == 11)
old = CL.MAX_ROWS; CL.MAX_ROWS = 5; lib.add([{"id": "n1", "text": "one more", "strength": 0.1}]); CL.MAX_ROWS = old
check("trim keeps the codex", lib.stats()["total"] == 5 and lib.search("Arasaka"), lib.stats())
# ---- through the proxy ----
import importlib, threading, urllib.request
os.environ.update(CYPHER_LIBRARY_DIR=os.path.join(T, "plib"), CYPHER_SYNC_DIR=os.path.join(T, "sync"),
                  CYPHER_PROXY_TOKEN_FILE=os.path.join(T, "tok"), CYPHER_PROXY_GAMING_CMD="false", CYPHER_PROXY_CAMERA_LOGS=os.path.join(T, "none"))
tok = "t" * 40
fd = os.open(os.path.join(T, "tok"), os.O_WRONLY | os.O_CREAT, 0o600); os.write(fd, tok.encode()); os.close(fd)
PX = importlib.import_module("cypher_brain_proxy")
import cypher_sync
PX.store = cypher_sync.Store(os.path.join(T, "sync"), 180); PX.library = CL.Library(os.path.join(T, "plib"))
from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", 0), PX.H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
def call(m, path, body=None, auth=True):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode() if body is not None else None, method=m,
                               headers=dict({"Content-Type": "application/json"}, **({"Authorization": "Bearer " + tok} if auth else {})))
    try:
        with urllib.request.urlopen(r, timeout=5) as resp: return resp.status, json.load(resp)
    except urllib.error.HTTPError as e: return e.code, None
check("no token -> 401", call("GET", "/library/stats", auth=False)[0] == 401)
check("POST /library/add", call("POST", "/library/add", {"holder": "cypher", "entries": rows[:3]}) == (200, {"added": 3}))
c, j = call("GET", "/library/search?q=Watson&limit=2"); check("GET /library/search", c == 200 and len(j["entries"]) == 2, j)
c, j = call("GET", "/library/wander?mode=old"); check("GET /library/wander", c == 200 and j["entries"], j)
check("POST /library/touch", call("POST", "/library/touch", {"ids": ["m0"]}) == (200, {"touched": 1}))
check("GET /library/stats", call("GET", "/library/stats")[1]["total"] == 3)
check("unknown library path -> 404", call("GET", "/library/drop")[0] == 404)
srv.shutdown()
print("%d passed, %d failed" % (P, F))
sys.exit(1 if F else 0)
