"""cypher_library - Cypher's library on Alpha (build 15). Stdlib only (sqlite3 + FTS5).

Everything Cypher lets go of from his small working memory, his journal pages, the
lore codex entries he writes and the things he makes are shelved here, each with its
date, place, mood and strength. The deck queues entries in an outbox and sends them
when Alpha is reachable; Alpha's standby writes here directly through the proxy.

  add(entries)          INSERT OR IGNORE by id (a resend is harmless)
  search(q, limit)      full-text search (FTS5, bm25 ranked, strength as tie-break)
  wander(mode, limit)   random shelves, or the oldest / least-visited ones
  touch(ids)            a find was read again: strength up, visit count up
  stats()               counts by kind, oldest/newest day

The database lives in ~/.local/share/cypher-library/library.db (0600). Text is
stored as sent (the deck already scrubbed it); nothing here is logged.
"""
import json, os, re, sqlite3, threading, time

KINDS = ("memory", "lesson", "journal", "found", "loop", "verdict", "codex", "made", "pino", "interview", "sleep", "talk", "thread",
         "rediscovered", "other")   # cypherd.LIB_KINDS plus a catch-all
MAX_TEXT = 4000
MAX_BATCH = 200
MAX_ROWS = 200000

SCHEMA = """
CREATE TABLE IF NOT EXISTS shelf (
  id TEXT PRIMARY KEY, ts TEXT, day TEXT, kind TEXT, place TEXT, mood TEXT,
  strength REAL, text TEXT, host TEXT, note TEXT, added REAL, visits INTEGER DEFAULT 0, last_visit REAL);
CREATE INDEX IF NOT EXISTS shelf_day ON shelf(day);
CREATE VIRTUAL TABLE IF NOT EXISTS shelf_fts USING fts5(text, kind, place, content='shelf', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS shelf_ai AFTER INSERT ON shelf BEGIN
  INSERT INTO shelf_fts(rowid, text, kind, place) VALUES (new.rowid, new.text, new.kind, new.place); END;
CREATE TRIGGER IF NOT EXISTS shelf_ad AFTER DELETE ON shelf BEGIN
  INSERT INTO shelf_fts(shelf_fts, rowid, text, kind, place) VALUES ('delete', old.rowid, old.text, old.kind, old.place); END;
"""
COLS = ("id", "ts", "day", "kind", "place", "mood", "strength", "text", "host", "note", "visits")

def _s(v, n):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", v)[:n] if isinstance(v, str) else ""

class Library:
    def __init__(self, root):
        os.makedirs(root, mode=0o700, exist_ok=True)
        self.path = os.path.join(root, "library.db")
        self.lock = threading.Lock()
        new = not os.path.exists(self.path)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        if new:
            os.chmod(self.path, 0o600)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def _row(self, r):
        return {k: r[i] for i, k in enumerate(COLS)}

    def add(self, entries, holder=None, now=None):
        if not isinstance(entries, list) or len(entries) > MAX_BATCH:
            raise ValueError("entries")
        now = now or time.time()
        n = 0
        with self.lock:
            for e in entries:
                if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not isinstance(e.get("text"), str) or not e["text"].strip():
                    continue
                try:
                    st = max(0.0, min(float(e.get("strength") or 1.0), 5.0))
                except (TypeError, ValueError):
                    st = 1.0
                kind = e.get("kind") if e.get("kind") in KINDS else "other"
                c = self.db.execute("INSERT OR IGNORE INTO shelf (id, ts, day, kind, place, mood, strength, text, host, note, added, visits)"
                                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                                    (_s(e["id"], 80), _s(e.get("ts"), 30), _s(e.get("day"), 10), kind, _s(e.get("place"), 30),
                                     _s(e.get("mood"), 20), st, _s(e["text"], MAX_TEXT), _s(e.get("host") or holder, 10),
                                     _s(e.get("note"), 120), now))
                n += c.rowcount
            self.db.commit()
            self._trim()
        return n

    def _trim(self):
        (cnt,) = self.db.execute("SELECT COUNT(*) FROM shelf").fetchone()
        if cnt > MAX_ROWS:      # the weakest, least-visited go first; never the codex or things he made
            self.db.execute("DELETE FROM shelf WHERE id IN (SELECT id FROM shelf WHERE kind NOT IN ('codex','made') "
                            "ORDER BY strength + visits * 0.5 ASC, added ASC LIMIT ?)", (cnt - MAX_ROWS,))
            self.db.commit()

    def search(self, q, limit=3):
        words = re.findall(r"[A-Za-z0-9']{2,}", q or "")[:8]
        if not words:
            return []
        fts = " OR ".join('"%s"' % w.replace('"', "") for w in words)
        limit = max(1, min(int(limit), 10))
        with self.lock:
            rows = self.db.execute("SELECT %s FROM shelf_fts JOIN shelf ON shelf.rowid = shelf_fts.rowid WHERE shelf_fts MATCH ? "
                                   "ORDER BY bm25(shelf_fts) - shelf.strength * 0.1 LIMIT ?" % ", ".join("shelf." + c for c in COLS),
                                   (fts, limit)).fetchall()
        return [self._row(r) for r in rows]

    def wander(self, mode="random", limit=2):
        limit = max(1, min(int(limit), 10))
        order = "day ASC, visits ASC" if mode == "old" else "RANDOM()"
        with self.lock:
            if mode == "old":      # the oldest quarter of the shelves, least visited first, a little shuffled
                rows = self.db.execute("SELECT %s FROM (SELECT * FROM shelf ORDER BY day ASC, visits ASC LIMIT 40) ORDER BY RANDOM() LIMIT ?"
                                       % ", ".join(COLS), (limit,)).fetchall()
            else:
                rows = self.db.execute("SELECT %s FROM shelf ORDER BY %s LIMIT ?" % (", ".join(COLS), order), (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def touch(self, ids, now=None):
        if not isinstance(ids, list):
            raise ValueError("ids")
        now = now or time.time()
        ids = [i for i in ids if isinstance(i, str)][:20]
        with self.lock:
            for i in ids:
                self.db.execute("UPDATE shelf SET visits = visits + 1, last_visit = ?, strength = MIN(5.0, strength + 0.3) WHERE id = ?", (now, i))
            self.db.commit()
        return len(ids)

    def stats(self):
        with self.lock:
            kinds = dict(self.db.execute("SELECT kind, COUNT(*) FROM shelf GROUP BY kind").fetchall())
            lo, hi = self.db.execute("SELECT MIN(day), MAX(day) FROM shelf").fetchone()
        return {"total": sum(kinds.values()), "kinds": kinds, "oldest": lo, "newest": hi}
