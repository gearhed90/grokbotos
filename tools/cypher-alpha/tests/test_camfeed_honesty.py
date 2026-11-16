#!/usr/bin/env python3
"""Phase 2.1: camfeed holds detector guesses until the Eufy routine's verdict.
Uses the real Nov 15 09:15/09:17 lines (camera pan over parked cars)."""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
T = tempfile.mkdtemp()
os.environ.update(CAMFEED_EUFY_DIR=os.path.join(T, "eufy"), CAMFEED_VISION_DIR=os.path.join(T, "vision"),
                  CAMFEED_OUT_DIR=os.path.join(T, "feed"), CAMFEED_NAMES=os.path.join(T, "names"), CAMFEED_HOLD_S="600")
sys.path[:0] = [os.path.join(ROOT, "camfeed")]
import cypher_camfeed as CF
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))
for d in ("eufy", "vision"): os.makedirs(os.path.join(T, d))
open(os.path.join(T, "names"), "w").write("Zack\nJessi\n")
dl, ql, cl, sl = (os.path.join(T, "eufy", "decisions.log"), os.path.join(T, "eufy", "quiet.log"),
                  os.path.join(T, "vision", "cloud-alerts.txt"), os.path.join(T, "vision", "shadow.log"))
for f in (dl, ql, cl, sl): open(f, "w").close()
feed = CF.Feed(); feed.poll(1000)
def add(path, line):
    with open(path, "a") as f: f.write(line + "\n")
gate = lambda t, clip, reason: json.dumps({"t": t, "camera": "front_door", "clip": clip + ".mp4", "trigger": "motion",
                                            "verdict": "pass", "stage": 2, "reason": reason, "top": ["car:0.80"]})
add(dl, gate("2026-11-15 09:18:56", "front_door-20261115-091737", "new car 0.60"))
check("gate 'new car' is held, not sent as vehicle", feed.poll(2000) == [] and "front_door-20261115-091737" in feed.st["pending"])
add(ql, "2026-11-15 09:19:44 ET front_door no-alert: camera pan only; gate 'new car' was Zack's parked sedan and parked white pickup, "
        "low-conf person was porch toy; no person front_door-20261115-091737")
evs = feed.poll(2100)
check("no-alert verdict -> one 'nothing' event", len(evs) == 1 and evs[0]["kind"] == "nothing", evs)
check("reason is fixed phrases only", evs and evs[0]["reason"] == "camera pan, parked cars only, false detection", evs)
check("no names, cars or free text leak", evs and "Zack" not in json.dumps(evs) and "sedan" not in json.dumps(evs) and "pickup" not in json.dumps(evs))
check("event keeps the gate's time and the folder id", evs and evs[0]["time"] == "2026-11-15 09:18:56" and evs[0]["id"] == "front_door-20261115-091737")
add(dl, gate("2026-11-15 10:00:00", "front_door-20261115-095950", "person 0.70"))
feed.poll(3000)
add(cl, "front_door-20261115-095950  # man in grey hoodie at the door, not family")
evs = feed.poll(3100)
check("cloud alert verdict -> alert, alerted", len(evs) == 1 and evs[0]["kind"] == "alert" and evs[0]["alerted"] is True and "hoodie" not in json.dumps(evs), evs)
add(dl, gate("2026-11-15 11:00:00", "basement-20261115-105955", "person 0.55").replace("front_door", "basement", 1))
add(sl, json.dumps({"gate_t": "2026-11-15 11:00:00", "camera": "basement", "event": "basement-20261115-105955", "status": "ok",
                    "person": True, "stranger": True, "alert": True, "reason": "unknown man"}))
check("shadow result is never an event of its own", feed.poll(4000) == [])
check("still held at 599 s", feed.poll(4599) == [])
evs = feed.poll(4600)
check("no verdict after 600 s -> unconfirmed with the guess", len(evs) == 1 and evs[0]["kind"] == "unconfirmed" and evs[0]["guess"] == "person"
      and evs[0]["camera"] == "basement" and not feed.st["pending"], evs)
add(ql, "2026-11-15 11:12:00 ET basement family: Jessi walking to her car basement-20261115-105955")
evs = feed.poll(4700)
check("late family verdict still goes out", len(evs) == 1 and evs[0]["kind"] == "family" and evs[0]["names"] == ["Jessi"], evs)
add(ql, "2026-11-15 12:00:00\tfront_door\t/home/gearhed/nova-snapshots/front_door-20261115-115950\t/clip.mp4\tperson 0.41")
add(dl, gate("2026-11-15 12:00:30", "front_door-20261115-120020", "person 0.5"))
feed.poll(5000); add(ql, "2026-11-15 12:01:00 ET front_door review note front_door-20261115-120020")
evs = feed.poll(5100)
check("an unrelated review note does not settle a held guess", "front_door-20261115-120020" in feed.st["pending"]
      and not any(e["kind"] in ("person", "vehicle", "unconfirmed") for e in evs), evs)
check("pending survives a restart", "front_door-20261115-120020" in (feed.save() or json.load(open(os.path.join(T, "feed", "offsets.json")))["pending"]))
out = [json.loads(l) for l in open(os.path.join(T, "feed", "events.jsonl"))]
check("feed fields allowlisted", all(set(e) <= {"seq", "time", "camera", "kind", "alerted", "source", "id", "names", "guess", "reason"} for e in out), out)
check("no path or URL in the feed", "/home" not in open(os.path.join(T, "feed", "events.jsonl")).read())
print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
