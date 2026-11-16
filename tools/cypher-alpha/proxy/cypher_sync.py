"""Mind lease and state/journal sync for Cypher, kept by cypher-brain-proxy on Alpha.

Exactly one cypherd thinks at a time: the one holding the lease.
  * "cypher" (the deck) is the primary. Its acquire always wins; if Alpha held
    the lease, the epoch goes up and Alpha's next renew is refused (hand-back).
  * "alpha" (the standby on Alpha) may take the lease only when it is free:
    released for hand-off (cypherd on the deck stopped cleanly, not with the
    kill switch), or expired (no renew for TTL seconds) AND the standby has
    checked that the deck itself does not answer (deck_unreachable). A lease
    released by the kill switch is "parked": nobody takes it until the deck
    acquires again.
  * Writes are fenced: only the current holder with the current epoch may save
    state. Journal entries from older epochs are kept as history.
Files (0600) under ~/.local/share/cypher-sync: lease.json, state.json, journal/YYYY-MM-DD.jsonl.
"""
import json, os, threading, time

HOLDERS = ("cypher", "alpha")
MAX_STATE = 512 * 1024      # build 15: state carries his mind (beliefs, working memory, lore)
MAX_ENTRIES = 200

def _write(path, obj):
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

class Store:
    def __init__(self, root, ttl=180.0):
        self.root = root; self.ttl = ttl
        os.makedirs(os.path.join(root, "journal"), mode=0o700, exist_ok=True)
        self.lock = threading.Lock()
        self._ids = {}

    # ---- lease ----
    def lease(self):
        return _read(os.path.join(self.root, "lease.json"),
                     {"holder": None, "epoch": 0, "expires": 0, "released": False, "parked": False})

    def _save_lease(self, l):
        _write(os.path.join(self.root, "lease.json"), l)

    def lease_op(self, holder, op, epoch=None, handoff=False, deck_unreachable=False, now=None):
        now = now or time.time()
        if holder not in HOLDERS or op not in ("acquire", "renew", "release", "status"):
            raise ValueError("bad lease request")
        with self.lock:
            l = self.lease()
            live = not l.get("released") and l.get("expires", 0) > now
            out = lambda granted, why="": dict({"granted": granted, "why": why, "now": now},
                                               **{k: l.get(k) for k in ("holder", "epoch", "expires", "released", "parked")})
            if op == "status":
                return out(False, "status")
            if op == "release":
                if l.get("holder") != holder or l.get("epoch") != epoch:
                    return out(False, "not_holder")
                l.update(released=True, expires=0, parked=not handoff)
                self._save_lease(l); return out(True, "released")
            if holder == "cypher":
                prev = l.get("holder")
                if prev != "cypher" or not live:
                    if prev != "cypher" or l.get("released") or epoch != l.get("epoch"):
                        l["epoch"] = int(l.get("epoch", 0)) + 1
                l.update(holder="cypher", expires=now + self.ttl, released=False, parked=False)
                self._save_lease(l)
                return out(True, "preempted_alpha" if prev == "alpha" and live else "primary")
            # holder == "alpha"
            if l.get("holder") == "alpha" and live:
                if epoch != l.get("epoch"):
                    return out(False, "stale_epoch")
                l["expires"] = now + self.ttl; self._save_lease(l); return out(True, "renewed")
            if op == "renew":
                return out(False, "lost")
            if l.get("parked"):
                return out(False, "parked")
            if live:
                return out(False, "deck_holds_lease")
            if not l.get("released") and not deck_unreachable:
                return out(False, "expired_but_deck_answers")
            l.update(holder="alpha", epoch=int(l.get("epoch", 0)) + 1, expires=now + self.ttl,
                     released=False, parked=False)
            self._save_lease(l); return out(True, "takeover")

    # ---- state ----
    def put_state(self, holder, epoch, state, now=None):
        if not isinstance(state, dict) or len(json.dumps(state)) > MAX_STATE:
            raise ValueError("bad state")
        with self.lock:
            l = self.lease()
            if l.get("holder") != holder or l.get("epoch") != epoch:
                return False
            _write(os.path.join(self.root, "state.json"),
                   {"holder": holder, "epoch": epoch, "saved": now or time.time(), "state": state})
            return True

    def get_state(self):
        return _read(os.path.join(self.root, "state.json"), {})

    # ---- journal ----
    def _day_ids(self, day):
        if day not in self._ids:
            ids = set()
            try:
                with open(os.path.join(self.root, "journal", day + ".jsonl")) as f:
                    for line in f:
                        try: ids.add(json.loads(line).get("id"))
                        except ValueError: pass
            except OSError:
                pass
            self._ids[day] = ids
        return self._ids[day]

    def append_journal(self, holder, epoch, entries):
        if holder not in HOLDERS or not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValueError("bad journal batch")
        n = 0
        with self.lock:
            if not isinstance(epoch, int) or epoch > int(self.lease().get("epoch", 0)):
                return 0
            for e in entries:
                if not isinstance(e, dict) or not isinstance(e.get("ts"), str) or len(e["ts"]) < 10:
                    continue
                e = dict(e); e["host"] = holder
                e["id"] = str(e.get("id") or "%s:%s:%s" % (holder, e["ts"], e.get("tick", e.get("event", ""))))[:80]
                day = e["ts"][:10]
                if not all(c.isdigit() or c == "-" for c in day):
                    continue
                ids = self._day_ids(day)
                if e["id"] in ids:
                    continue
                with open(os.open(os.path.join(self.root, "journal", day + ".jsonl"),
                                  os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as f:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
                ids.add(e["id"]); n += 1
        return n

    def get_journal(self, since="", host=None, limit=500):
        out = []
        d = os.path.join(self.root, "journal")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".jsonl") or name[:10] < since[:10]:
                continue
            with open(os.path.join(d, name)) as f:
                for line in f:
                    try: e = json.loads(line)
                    except ValueError: continue
                    if e.get("ts", "") > since and (host is None or e.get("host") == host):
                        out.append(e)
        out.sort(key=lambda e: e.get("ts", ""))
        return out[:limit]
