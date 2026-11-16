"""cypher_journal - Cypher's journal as readable entries (build 14; stdlib only).

Shared by the HUD's journal viewer (nova_native: tap the JOURNAL panel or press Super+J) and
`grokbot-cypher journal`. Reads ~/.local/share/cypher/journal/*.jsonl read-only, newest first, and
turns each line into {time, kind, what, reason, result, extra}: what Cypher did or thought, why, and
how it turned out. Every string is scrubbed (links, emails, addresses, tokens, house device ids)
before it is shown, the same rules as the panels and cypherd.dash_text."""
import json, os, re

E = os.environ.get
HOME = os.path.expanduser("~")
DATA_DIR = E("CYPHER_DATA_DIR", os.path.join(E("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "cypher"))
MAX_LINE = 65536
FULL = 4000          # build 15: conversations and thoughts are kept and shown in full (was cut at 600 / 300)

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_SCRUB = [
    (re.compile(r"\b(?:token|api[_ -]?key|password|passwd|secret|topic)\s*[:=]\s*\S+", re.I), "[redacted]"),
    (re.compile(r"\b(?:https?|rtsp|rtsps|wss?|mqtt)://\S+|www\.\S+", re.I), "[link]"),
    (re.compile(r"s4j6vbnk\+cypher@mail\.grokbot\.com|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I), "[email]"),
    (re.compile(r"\b(?:light|switch|camera|lock|cover|alarm_control_panel|binary_sensor|sensor|automation|script|scene|"
                r"input_\w+|media_player|climate|fan|siren|button|select|number)\.[a-z0-9_]+", re.I), "[device]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "[addr]"),
    (re.compile(r"\b(?:cypher-[A-Za-z0-9_-]{6,}|xai-[A-Za-z0-9_-]{6,}|Bearer\s+\S+|eyJ[\w-]{8,}\S*|[A-Za-z0-9_+/=-]{20,})"), "[redacted]"),
]

def scrub(t, n=600):
    t = _CTRL.sub(" ", t if isinstance(t, str) else ("" if t is None else str(t)))
    for rx, sub in _SCRUB:
        t = rx.sub(sub, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n - 1] + "\u2026"

def _hm(ts):
    """'7:05 PM' from the journal's local ISO time (America/New_York, with its offset)."""
    m = re.match(r"^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", str(ts or ""))
    if not m:
        return "?"
    h, mi = int(m.group(1)), m.group(2)
    return "%d:%s %s ET" % (h % 12 or 12, mi, "AM" if h < 12 else "PM")

def view(e):
    """One journal entry as a readable dict, or None if it is not worth showing."""
    if not isinstance(e, dict):
        return None
    ts = str(e.get("ts", ""))
    out = {"ts": ts[:19], "day": ts[:10], "time": _hm(ts), "kind": "event", "what": "", "reason": "", "result": "", "extra": "",
           "host": "alpha" if e.get("host") == "alpha" else "deck"}
    ev = e.get("event")
    if ev == "talk":
        out.update(kind="talk", what="Zack: %s" % scrub(e.get("user"), FULL), result="Cypher: %s" % scrub(e.get("reply"), FULL))
        tools = [t.get("tool") for t in e.get("tools") or [] if isinstance(t, dict)]
        if tools: out["extra"] = "tools: " + ", ".join(scrub(t, 30) for t in tools)
        return out
    if ev == "talk_action":
        out.update(kind="ask", what="asked on screen: %s %s" % (scrub(e.get("action"), 30), scrub(e.get("arg") or e.get("service") or "", 80)),
                   result=scrub(e.get("validator"), 120) + ("; found: " + scrub(e["found"]) if e.get("found") else ""))
        return out
    if ev == "interview":
        out.update(kind="interview", what="%s: %s" % (scrub(e.get("asker") or "Nova", 10), scrub(e.get("question"), FULL)),
                   result="Cypher: %s" % scrub(e.get("answer"), FULL), extra=("brain: %s" % scrub(e.get("brain"), 12)) if e.get("brain") else "")
        return out
    if ev:
        bits = []
        for k in ("why", "changes", "key", "count", "from", "to", "service", "summary", "question", "title", "day", "memories"):
            v = e.get(k)
            if v not in (None, "", []):
                s = scrub("; ".join(str(x) for x in v) if isinstance(v, list) else v, 300)
                bits.append(s if k == "why" else "%s: %s" % (k, s))
        out.update(kind="event", what=scrub(str(ev).replace("_", " "), 60), reason=" | ".join(bits))
        return out
    ch = e.get("choice") or {}
    a = str(ch.get("action") or "none")
    pr = ch.get("params") if isinstance(ch.get("params"), dict) else {}
    v = str(e.get("validator", ""))
    arg = pr.get("text") or pr.get("topic") or pr.get("query") or pr.get("handle") or pr.get("place") or pr.get("color") \
        or pr.get("service") or pr.get("question") or pr.get("title") or ""
    if v.startswith("rejected"):
        out.update(kind="refused", what="tried %s%s" % (scrub(e.get("model_choice") or a, 40), (": " + scrub(arg, 200)) if arg else ""))
    elif a == "journal_thought":
        out.update(kind="thought", what=scrub(arg, FULL))
    elif a == "none":
        if (e.get("perception") or {}).get("camera"):
            out.update(kind="camera", what="saw the cameras, let it be")
        else:
            out.update(kind="idle", what="did nothing")
    else:
        out.update(kind=a, what=a.replace("_", " ") + ((": " + scrub(arg)) if arg else ""))
    out["reason"] = scrub(e.get("reason"))
    res = []
    if v and v != "ok": res.append(scrub(v, 200))
    r = str(e.get("result", ""))
    if r and r not in ("ok", "ok (dry run)", "skipped"): res.append(scrub(r, 200))
    if e.get("found"): res.append("found: " + scrub(e["found"]))
    if e.get("said"): res.append(scrub(e["said"], 200))
    out["result"] = " | ".join(res) or ("done" if v == "ok" and a != "none" else "")
    extra = [x for x in (e.get("note"), e.get("retry"), e.get("thread")) if x]
    if e.get("brain"): extra.insert(0, "brain: %s" % scrub(e["brain"], 12))
    out["extra"] = " | ".join(scrub(x, 200) for x in extra)
    return out

def files(data_dir=None):
    d = os.path.join(data_dir or DATA_DIR, "journal")
    try:
        return [os.path.join(d, f) for f in sorted(os.listdir(d), reverse=True) if re.match(r"^\d{4}-\d{2}-\d{2}\.jsonl$", f)]
    except OSError:
        return []

CHAT_KINDS = ("talk", "ask", "interview")

def entries(limit=200, offset=0, data_dir=None, kinds=None):
    """Readable entries, newest first: `limit` of them after skipping `offset` (for scrolling back).
    kinds: only these (e.g. CHAT_KINDS for the conversation view)."""
    out, skip = [], offset
    for path in files(data_dir):
        try:
            with open(path, errors="replace") as f:
                lines = [l for l in f.read().splitlines() if l.strip()][-5000:]
        except OSError:
            continue
        rows = []
        for l in lines:
            if len(l) > MAX_LINE:
                continue
            try:
                v = view(json.loads(l))
            except ValueError:
                continue
            if v and (not kinds or v["kind"] in kinds):
                rows.append(v)
        rows.sort(key=lambda r: r["ts"], reverse=True)   # Alpha's merged entries arrive out of order
        for r in rows:
            if skip:
                skip -= 1; continue
            out.append(r)
            if len(out) >= limit:
                return out
    return out

def text(v, width=None):
    """Plain text block for one entry (the CLI)."""
    head = "%s %s  %s%s" % (v["day"], v["time"], v["kind"].upper(), " @alpha" if v["host"] == "alpha" else "")
    lines = [head, "  " + v["what"]]
    if v["reason"]: lines.append("  why: " + v["reason"])
    if v["result"]: lines.append(("  " if v["kind"] in ("talk", "interview") else "  result: ") + v["result"])
    if v["extra"]: lines.append("  " + v["extra"])
    if width:
        import textwrap
        lines = [head] + [textwrap.fill(l, width, subsequent_indent="    ") for l in lines[1:]]
    return "\n".join(lines)
