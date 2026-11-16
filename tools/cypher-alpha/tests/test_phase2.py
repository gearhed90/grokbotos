#!/usr/bin/env python3
"""Phase 2 tests on Alpha: mind lease + sync store, camfeed sanitizer, proxy endpoints. No GPU, no network."""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "proxy"), os.path.join(ROOT, "camfeed")]
T = tempfile.mkdtemp()
os.environ.update(CAMFEED_EUFY_DIR=os.path.join(T, "eufy"), CAMFEED_VISION_DIR=os.path.join(T, "vision"),
                  CAMFEED_OUT_DIR=os.path.join(T, "feed"), CAMFEED_NAMES=os.path.join(T, "names"), CAMFEED_BACKFILL="2")
import cypher_sync, cypher_camfeed as CF
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))

# ---- lease ----
S = cypher_sync.Store(os.path.join(T, "sync"), ttl=180); t = 1000.0
r = S.lease_op("cypher", "acquire", None, now=t); check("deck takes a free lease", r["granted"] and r["epoch"] == 1, r)
e1 = r["epoch"]
r = S.lease_op("cypher", "renew", e1, now=t + 45); check("deck renew keeps the epoch", r["granted"] and r["epoch"] == e1, r)
r = S.lease_op("alpha", "acquire", None, deck_unreachable=True, now=t + 60); check("standby cannot take a live lease", not r["granted"] and r["why"] == "deck_holds_lease", r)
r = S.lease_op("alpha", "acquire", None, now=t + 400); check("expired but deck answers -> no takeover", not r["granted"] and r["why"] == "expired_but_deck_answers", r)
r = S.lease_op("alpha", "acquire", None, deck_unreachable=True, now=t + 400); check("expired + deck unreachable -> takeover, epoch+1", r["granted"] and r["epoch"] == 2, r)
check("only the holder may save state", S.put_state("alpha", 2, {"x": 1}) and not S.put_state("cypher", 1, {"x": 2}))
r = S.lease_op("alpha", "renew", 2, now=t + 440); check("standby renews", r["granted"], r)
r = S.lease_op("cypher", "acquire", e1, now=t + 450); check("deck back -> preempts, epoch+1", r["granted"] and r["epoch"] == 3 and r["why"] == "preempted_alpha", r)
r = S.lease_op("alpha", "renew", 2, now=t + 460); check("standby's next renew is refused (hand-back)", not r["granted"] and r["why"] == "lost", r)
check("fenced: standby's late state write refused", not S.put_state("alpha", 2, {"late": 1}))
check("state from the epoch-2 holder is still the saved one until the deck writes", S.get_state()["epoch"] == 2)
check("deck saves state", S.put_state("cypher", 3, {"drives": {"energy": 0.5}}) and S.get_state()["holder"] == "cypher")
r = S.lease_op("cypher", "release", 3, handoff=True, now=t + 470); check("clean stop releases for hand-off", r["granted"] and not r["parked"], r)
r = S.lease_op("alpha", "acquire", None, now=t + 471); check("released lease -> standby takes it at once", r["granted"] and r["epoch"] == 4, r)
r = S.lease_op("cypher", "acquire", 3, now=t + 500); check("deck takes it back", r["granted"] and r["epoch"] == 5, r)
r = S.lease_op("cypher", "release", 5, handoff=False, now=t + 510); check("kill switch parks the lease", r["parked"], r)
r = S.lease_op("alpha", "acquire", None, deck_unreachable=True, now=t + 9999); check("parked lease: standby never takes it", not r["granted"] and r["why"] == "parked", r)
r = S.lease_op("cypher", "acquire", 5, now=t + 10000); check("deck unparks by acquiring", r["granted"] and not r["parked"], r)
check("release by a non-holder refused", not S.lease_op("alpha", "release", 6)["granted"])
try: S.lease_op("mallory", "acquire"); check("unknown holder refused", False)
except ValueError: check("unknown holder refused", True)
try: S.put_state("cypher", 6, {"big": "x" * 600000}); check("oversized state refused", False)
except ValueError: check("oversized state refused", True)

# ---- journal sync ----
ents = [{"ts": "2026-11-15T03:00:00-0500", "tick": 1, "reason": "a"}, {"ts": "2026-11-15T03:01:00-0500", "tick": 2}]
check("journal batch added", S.append_journal("alpha", 4, ents) == 2)
check("journal dedup by id", S.append_journal("alpha", 4, ents) == 0)
check("future epoch refused", S.append_journal("alpha", 99, [{"ts": "2026-11-15T03:05:00-0500", "tick": 9}]) == 0)
S.append_journal("cypher", 6, [{"ts": "2026-11-15T03:02:00-0500", "tick": 7}])
j = S.get_journal("2026-11-15T03:00:30-0500", "alpha"); check("journal since + host filter", len(j) == 1 and j[0]["tick"] == 2, j)
check("entries carry host", all(e["host"] for e in S.get_journal("")))
check("bad day key ignored", S.append_journal("cypher", 6, [{"ts": "../../etc/x-yy"}]) == 0)
check("sync files are private", all(os.stat(os.path.join(dp, f)).st_mode & 0o077 == 0
      for dp, _, fs in os.walk(os.path.join(T, "sync")) for f in fs))

# ---- camfeed sanitizer ----
names = ["Zack", "Brody", "Abel", "Jessi"]
g = CF.sanitize("gate", json.dumps({"t": "2026-11-14 20:11:18", "camera": "front_door", "clip": "front_door-20261114-201112.mp4",
    "verdict": "pass", "reason": "person 0.69", "top": "['person:0.69']", "folder": "/home/gearhed/nova-snapshots/x"}), names)
check("gate pass -> person, allowlisted fields only", g == {"time": "2026-11-14 20:11:18", "camera": "front_door", "kind": "person",
      "alerted": None, "source": "gate", "id": "front_door-20261114-201112"}, g)
check("gate drop -> motion_dropped, not alerted", CF.sanitize("gate", json.dumps({"t": "2026-11-14 20:00:00", "camera": "basement",
      "verdict": "drop", "clip": "basement-20261114-200000.mp4"}), names)["alerted"] is False)
check("gate lights/preset lines dropped", CF.sanitize("gate", json.dumps({"t": "2026-11-14 20:00:00", "camera": "arrival",
      "verdict": "lights-skip", "reason": "x"}), names) is None)
q = CF.sanitize("review", "2026-11-14 08:10 PM ET front_door family: Zack (beard, olive tee, jeans) walked up with Jill and a stranger; "
                "red car front_door-20261114-201029 /home/gearhed/nova-snapshots/a.jpg", names)
check("review -> family + first names, no description", q["kind"] == "family" and q["names"] == ["Zack"] and q["time"] == "2026-11-14 20:10:00"
      and "olive" not in json.dumps(q) and "nova-snapshots" not in json.dumps(q) and "Jill" not in json.dumps(q), q)
check("review no-alert -> alerted false", CF.sanitize("review", "2026-11-14 20:11:48 ET basement no-alert: car basement-20261114-201029", names)["alerted"] is False)
sh = CF.sanitize("shadow", json.dumps({"gate_t": "2026-11-13 20:44:37", "camera": "front_door", "event": "front_door-20261113-204433",
     "status": "ok", "person": True, "stranger": True, "alert": True, "reason": "unknown man in hoodie", "folder": "/x"}), names)
check("shadow stranger alerted, reason dropped", sh["kind"] == "stranger" and sh["alerted"] is True and "hoodie" not in json.dumps(sh), sh)
check("shadow skipped_gaming dropped", CF.sanitize("shadow", json.dumps({"status": "skipped_gaming", "camera": "front_door"}), names) is None)
c = CF.sanitize("cloud", "basement-20261113-165113  # bright blue sedan (likely Jessi) leaving", names)
check("cloud alert -> time from id, names allowlisted", c["alerted"] is True and c["time"] == "2026-11-13 16:51:13" and c["names"] == ["Jessi"]
      and "sedan" not in json.dumps(c), c)
check("bad camera name refused", CF.sanitize("gate", json.dumps({"t": "2026-11-14 20:00:00", "camera": "../x", "verdict": "drop"}), names) is None)
check("garbage line ignored", CF.sanitize("gate", "not json", names) is None and CF.sanitize("review", "hello", names) is None)
check("names must look like first names", (open(os.environ["CAMFEED_NAMES"], "w").write("Zack\nBrody\nrm -rf /\nhttp://x\n") and CF.family_names() == ["Zack", "Brody"]))

# ---- camfeed tailing ----
os.makedirs(os.path.join(T, "eufy")); os.makedirs(os.path.join(T, "vision"))
dl = os.path.join(T, "eufy", "decisions.log")
with open(dl, "w") as f:
    for i in range(5):
        f.write(json.dumps({"t": "2026-11-14 20:0%d:00" % i, "camera": "front_door", "verdict": "drop", "clip": "front_door-20261114-200%d00.mp4" % i}) + "\n")
feed = CF.Feed(); n1 = len(feed.poll()); check("first run backfills only a little", n1 == 2, n1)
with open(dl, "a") as f:
    f.write(json.dumps({"t": "2026-11-14 21:00:00", "camera": "front_door", "verdict": "pass", "reason": "person 0.9", "clip": "front_door-20261114-210000.mp4"}) + "\n")
    f.write('{"t": "2026-11-14 21:00:05", "camera": "fro')                                   # half-written line
evs = feed.poll(); check("new whole lines only; a gate pass is held for the routine's verdict", evs == [] and "front_door-20261114-210000" in feed.st["pending"], evs)
with open(dl, "a") as f: f.write('nt_door", "verdict": "drop", "clip": "front_door-20261114-210005.mp4"}\n')
evs = feed.poll(); check("half line picked up once complete", len(evs) == 1 and evs[0]["time"] == "2026-11-14 21:00:05", evs)
with open(os.path.join(T, "eufy", "quiet.log"), "w") as f:
    f.write("2026-11-14 21:01:30 ET front_door family: Zack (olive tee) on the porch front_door-20261114-210000\n")
evs = feed.poll(); check("verdict releases it as family, at the gate's time", len(evs) == 1 and evs[0]["kind"] == "family" and evs[0]["names"] == ["Zack"]
      and evs[0]["time"] == "2026-11-14 21:00:00" and not feed.st["pending"], evs)
lines = [json.loads(l) for l in open(os.path.join(T, "feed", "events.jsonl"))]
check("events numbered", [e["seq"] for e in lines] == [1, 2, 3, 4], lines)
check("feed file private", os.stat(os.path.join(T, "feed", "events.jsonl")).st_mode & 0o077 == 0)
check("camfeed source never opens logs for writing", "open(path, \"w" not in open(CF.__file__).read() and "'a'" not in open(CF.__file__).read())

# ---- proxy endpoints ----
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port(); tok = os.path.join(T, "token"); TOKEN = "q" * 48
with open(tok, "w") as f: f.write(TOKEN)
os.chmod(tok, 0o600)
env = dict(os.environ, CYPHER_PROXY_UPSTREAM="http://127.0.0.1:1", CYPHER_PROXY_BIND="127.0.0.1", CYPHER_PROXY_PORT=str(port),
           CYPHER_PROXY_TOKEN_FILE=tok, CYPHER_PROXY_CAMERA_LOGS=dl, CYPHER_PROXY_GAMING_CMD="false",
           CYPHER_SYNC_DIR=os.path.join(T, "psync"), CYPHER_CAMFEED_FILE=os.path.join(T, "feed", "events.jsonl"))
p = subprocess.Popen([sys.executable, os.path.join(ROOT, "proxy", "cypher_brain_proxy.py")], env=env, stderr=subprocess.PIPE, text=True)
for _ in range(50):
    try: socket.create_connection(("127.0.0.1", port), 0.2).close(); break
    except OSError: time.sleep(0.1)
def call(path, body=None, token=TOKEN):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode() if body is not None else None,
                               headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
check("camera events need the token", call("/camera/events", token=None)[0] == 401)
check("lease needs the token", call("/lease", {"holder": "cypher", "op": "acquire"}, token="x" * 48)[0] == 401)
c, j = call("/camera/events?since=2"); check("camera events since seq", c == 200 and [e["seq"] for e in j["events"]] == [3, 4] and j["last_seq"] == 4, j)
check("camera event fields allowlisted", all(set(e) <= {"seq", "time", "camera", "kind", "alerted", "source", "id", "names"} for e in j["events"]))
c, j = call("/lease", {"holder": "cypher", "op": "acquire"}); check("lease over HTTP", c == 200 and j["granted"] and j["epoch"] == 1, j)
c, j = call("/sync/state", {"holder": "cypher", "epoch": 1, "state": {"drives": {"energy": 0.4}}}); check("state push", c == 200 and j["saved"], j)
c, j = call("/sync/state", {"holder": "alpha", "epoch": 1, "state": {}}); check("state push from non-holder -> 409", c == 409, j)
c, j = call("/sync/state"); check("state pull", j["saved"]["state"]["drives"]["energy"] == 0.4 and j["lease"]["holder"] == "cypher", j)
c, j = call("/sync/journal", {"holder": "cypher", "epoch": 1, "entries": [{"ts": "2026-11-15T04:00:00-0500", "tick": 3, "reason": "secret-thought"}]})
check("journal push", c == 200 and j["added"] == 1, j)
c, j = call("/sync/journal?since=2026-11-15T00:00:00-0500&host=cypher"); check("journal pull", len(j["entries"]) == 1, j)
c, j = call("/lease", {"holder": "cypher", "op": "nonsense"}); check("bad lease op -> 400", c == 400, j)
p.terminate(); err = p.communicate(timeout=10)[1]
check("journal text and token never in the proxy log", "secret-thought" not in err and TOKEN not in err, err[-300:])
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
