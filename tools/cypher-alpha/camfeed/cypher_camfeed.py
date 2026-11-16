#!/usr/bin/env python3
"""cypher-camfeed - read-only, sanitized camera events for Cypher (stdlib only).

Tails the camera pipeline's logs on Alpha and writes one allowlisted JSON line per
event to ~/.local/share/cypher-camfeed/events.jsonl. cypher-brain-proxy serves
that file at GET /camera/events. Nothing else leaves this process.

Read-only: it opens the logs for reading and never writes to, signals or calls
the camera pipeline, Home Assistant, the cameras or the lights.

Fields kept (everything else is dropped): seq, time, camera, kind, alerted,
source, id, first names from the family allowlist
(~/.config/cypher-camfeed/family_names, one per line), a detector "guess"
(person/vehicle/motion) and, for "nothing" events, a "reason" made only from a
fixed list of short phrases. Descriptions, clothing, vehicles, free-text
reasons, scores, file paths, folders, images and URLs never pass.

Honesty (Nov 15 2026): a gate "pass" is only the detector's guess, so it is held
until the Eufy routine's verdict for that snapshot folder (keyed by
<camera>-<YYYYMMDD-HHMMSS>) shows up: quiet.log "no-alert" -> kind "nothing"
(cypherd never reacts to it), quiet.log "family:" -> "family" with first names,
cloud-alerts.txt -> "alert". With no verdict after HOLD_S seconds it goes out as
"unconfirmed" with the detector's guess. Shadow-model results only sharpen that
guess; they are never events of their own.

Sources:
  decisions.log      eufy gate verdicts (JSON lines)                source "gate"
  quiet.log          vision reviewer's notes (free text)            source "review"
  shadow.log         shadow model results (JSON lines)              source "shadow"
  cloud-alerts.txt   event ids the cloud reviewer alerted Zack on   source "cloud"
"""
import json, os, re, sys, time

E = os.environ.get
HOME = os.path.expanduser("~")
EUFY = os.path.expanduser(E("CAMFEED_EUFY_DIR", "~/nova-projects/eufy-filter"))
VISION = os.path.expanduser(E("CAMFEED_VISION_DIR", "~/nova-projects/alpha-vision-model"))
OUT_DIR = os.path.expanduser(E("CAMFEED_OUT_DIR", "~/.local/share/cypher-camfeed"))
NAMES_FILE = os.path.expanduser(E("CAMFEED_NAMES", "~/.config/cypher-camfeed/family_names"))
POLL_S = float(E("CAMFEED_POLL_S", "10"))
BACKFILL = int(E("CAMFEED_BACKFILL", "8"))      # lines per source read on the very first run
HOLD_S = float(E("CAMFEED_HOLD_S", "600"))       # wait this long for the routine's verdict on a gate pass
KEEP = 2000

SOURCES = {
    "gate": os.path.join(EUFY, "decisions.log"),
    "review": os.path.join(EUFY, "quiet.log"),
    "shadow": os.path.join(VISION, "shadow.log"),
    "cloud": os.path.join(VISION, "cloud-alerts.txt"),
}
CAMERA_RE = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
EVENT_ID_RE = re.compile(r"\b([a-z][a-z0-9_]{0,19}-\d{8}-\d{6})\b")
INCIDENT_RE = re.compile(r"^[0-9a-f]{8}$")
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})")
KINDS = {"person", "vehicle", "motion", "stranger", "family", "nothing", "motion_dropped", "cooldown",
         "arrival_start", "arrival_end", "cross_trigger", "no_alert", "review", "alert", "unconfirmed"}
GUESS_KINDS = ("person", "vehicle", "motion")
# no-alert reasons -> fixed phrases (nothing else of the reviewer's text passes)
REASON_PHRASES = ((r"\bpan", "camera pan"), (r"parked", "parked cars only"),
                  (r"reflect|timestamp|toy|statue|shadow|glare|insect|bug|spider|rain|snow|headlight|leaves|wind", "false detection"),
                  (r"empty|no person|nobody|no one", "empty scene"), (r"passing|street|road", "passing traffic"))

def reason_of(text):
    low = (text or "").lower()
    out = [p for rx, p in REASON_PHRASES if re.search(rx, low)][:3]
    return ", ".join(out) or "nothing of note"

def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, file=sys.stderr, flush=True)

def family_names():
    try:
        with open(NAMES_FILE) as f:
            return [n.strip() for n in f if re.fullmatch(r"[A-Z][a-z]{1,15}", n.strip())]
    except OSError:
        return []

def names_in(text, names):
    return [n for n in names if re.search(r"\b%s\b" % re.escape(n), text or "")][:4]

def _event(t, camera, kind, alerted, source, eid, names=()):
    if not (isinstance(camera, str) and CAMERA_RE.match(camera)) or kind not in KINDS:
        return None
    if not (isinstance(t, str) and TIME_RE.match(t)):
        return None
    if eid is not None and not (EVENT_ID_RE.fullmatch(eid) or INCIDENT_RE.match(eid)):
        eid = None
    ev = {"time": t[:19], "camera": camera, "kind": kind,
          "alerted": alerted if isinstance(alerted, bool) else None, "source": source, "id": eid}
    if names:
        ev["names"] = list(names)
    return ev

def _clip_id(clip):
    m = EVENT_ID_RE.search(str(clip or ""))
    return m.group(1) if m else None

def _id_time(eid):
    m = re.search(r"-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$", eid or "")
    return "%s-%s-%s %s:%s:%s" % m.groups() if m else None

GATE_KINDS = {"drop": ("motion_dropped", False), "quiet": ("cooldown", False),
              "arrival-start": ("arrival_start", None), "arrival-end": ("arrival_end", None),
              "vehicle-window": ("vehicle", None), "cross-start": ("cross_trigger", None)}

def from_gate(line, names):
    j = json.loads(line)
    v = j.get("verdict")
    if v == "pass":
        r = str(j.get("reason", "")).lower()
        kind, alerted = ("person" if "person" in r else "vehicle" if re.search(r"car|truck|vehicle", r) else "motion"), None
    elif v in GATE_KINDS:
        kind, alerted = GATE_KINDS[v]
    else:
        return None
    eid = j.get("incident") if INCIDENT_RE.match(str(j.get("incident", ""))) else _clip_id(j.get("clip") or j.get("source_clip"))
    return _event(j.get("t"), j.get("camera"), kind, alerted, "gate", eid)

def from_review(line, names):
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?", line)
    if not m:
        return None
    d, h, mi, s, ap = m.groups()
    h = int(h)
    if ap == "PM" and h < 12: h += 12
    if ap == "AM" and h == 12: h = 0
    t = "%s %02d:%s:%s" % (d, h, mi, s or "00")
    cam = re.search(r"\b(front_door|basement|arrival|[a-z]+_[a-z]+)\b", line)
    eid = _clip_id(line)
    camera = cam.group(1) if cam else (eid.rsplit("-", 2)[0] if eid else None)
    low = line.lower()
    kind = "family" if "family:" in low else "nothing" if "no-alert" in low else "review"
    # names only for family verdicts: "no-alert: Zack's parked car" must not read as Zack being there
    ev = _event(t, camera, kind, False if kind == "nothing" else None, "review", eid,
                names_in(line, names) if kind == "family" else ())
    if ev and kind == "nothing":
        ev["reason"] = reason_of(line.split("no-alert", 1)[1])
    return ev

def from_shadow(line, names):
    j = json.loads(line)
    if j.get("status") != "ok":
        return None
    kind = ("stranger" if j.get("stranger") else "person" if j.get("person") else
            "vehicle" if j.get("vehicle_moving") or j.get("vehicle") else "nothing")
    return _event(str(j.get("gate_t") or j.get("logged") or ""), j.get("camera"), kind,
                  bool(j.get("alert")), "shadow", _clip_id(j.get("event")))

def from_cloud(line, names):
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    eid = _clip_id(s.split()[0])
    if not eid:
        return None
    comment = s.split("#", 1)[1] if "#" in s else ""
    return _event(_id_time(eid), eid.rsplit("-", 2)[0], "alert", True, "cloud", eid, names_in(comment, names))

PARSERS = {"gate": from_gate, "review": from_review, "shadow": from_shadow, "cloud": from_cloud}

def sanitize(source, line, names):
    try:
        return PARSERS[source](line, names)
    except (ValueError, TypeError, AttributeError, KeyError):
        return None

class Feed:
    def __init__(self):
        os.makedirs(OUT_DIR, mode=0o700, exist_ok=True)
        self.out = os.path.join(OUT_DIR, "events.jsonl")
        self.state_path = os.path.join(OUT_DIR, "offsets.json")
        try:
            with open(self.state_path) as f:
                self.st = json.load(f)
        except (OSError, ValueError):
            self.st = {"seq": 0, "files": {}}

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(self.st, f)
        os.replace(tmp, self.state_path)

    def new_lines(self, source, path):
        try:
            st = os.stat(path)
        except OSError:
            return []
        rec = self.st["files"].get(source)
        if rec is None or rec.get("ino") != st.st_ino or rec.get("off", 0) > st.st_size:
            first = rec is None
            with open(path, "rb") as f:
                data = f.read()
            lines = data.decode("utf-8", "replace").splitlines()
            self.st["files"][source] = {"ino": st.st_ino, "off": len(data)}
            return lines[-BACKFILL:] if first else lines      # first run: a little history; rotated: all
        with open(path, "rb") as f:
            f.seek(rec["off"])
            data = f.read()
        cut = data.rfind(b"\n") + 1                            # only whole lines
        rec["off"] += cut
        return data[:cut].decode("utf-8", "replace").splitlines()

    def resolve(self, ev, now):
        """Hold detector guesses until the routine's verdict; returns the events to write now."""
        pend = self.st.setdefault("pending", {})
        eid = ev.get("id")
        clip = eid if eid and EVENT_ID_RE.fullmatch(eid) else None
        if ev["source"] == "gate" and ev["kind"] in GUESS_KINDS:
            if not clip:
                return [dict(ev, kind="unconfirmed", guess=ev["kind"])]
            pend[clip] = {"ev": ev, "guess": ev["kind"], "at": now}
            return []
        if ev["source"] == "shadow":
            if clip in pend and ev["kind"] in ("person", "stranger", "vehicle"):
                pend[clip]["guess"] = "person" if ev["kind"] == "stranger" else ev["kind"]
            return []                                   # model guesses are never events of their own
        if clip in pend and ev["kind"] in ("nothing", "family", "alert"):
            g = pend.pop(clip)["ev"]
            out = dict(ev, time=g["time"], camera=g["camera"], id=clip)
            return [out]
        return [ev]

    def expire(self, now):
        pend = self.st.setdefault("pending", {})
        out = []
        for clip in sorted(pend, key=lambda c: pend[c]["ev"]["time"]):
            p = pend[clip]
            if now - p.get("at", now) >= HOLD_S:
                out.append(dict(p["ev"], kind="unconfirmed", guess=p.get("guess", "motion")))
                del pend[clip]
        while len(pend) > 200:
            del pend[min(pend, key=lambda c: pend[c]["at"])]
        return out

    def poll(self, now=None):
        now = now or time.time()
        names = family_names()
        evs = []
        for source, path in SOURCES.items():
            for line in self.new_lines(source, path):
                ev = sanitize(source, line, names)
                if ev:
                    evs.extend(self.resolve(ev, now))
        evs.extend(self.expire(now))
        evs.sort(key=lambda e: e["time"])
        if evs:
            with open(os.open(self.out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as f:
                for ev in evs:
                    self.st["seq"] += 1
                    f.write(json.dumps(dict(ev, seq=self.st["seq"])) + "\n")
            self.trim()
        self.save()
        return evs

    def trim(self):
        with open(self.out) as f:
            lines = f.readlines()
        if len(lines) > 2 * KEEP:
            tmp = self.out + ".tmp"
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.writelines(lines[-KEEP:])
            os.replace(tmp, self.out)

def main():
    feed = Feed()
    log("cypher-camfeed up, %d family names allowed" % len(family_names()))
    while True:
        try:
            n = len(feed.poll())
            if n:
                log("%d new events (seq %d)" % (n, feed.st["seq"]))
        except Exception as e:
            log("poll error:", type(e).__name__)
        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
