#!/usr/bin/env python3
"""cypher_panels - Cypher's state drawn as panels around the avatar (phase 4b).

The avatar screen (nova_native.py, app_id nova-shell) is Cypher's face; these panels
are its HUD: a left column (name, brain badge, mood and five drive meters, what it
is doing, the camera line, Zack's phone replies and pending account requests) and
a right column (clock and flags, the journal, recent actions with refusals). The
centre stays the avatar and the text bar. Super+C hides or shows them
(~/.config/cypher/panels-hidden).

Data: only ~/.local/state/cypher/dash.json, the display-only snapshot cypherd writes
every loop with every string scrubbed (cypherd.dash_text). This module scrubs again
before drawing and never opens a secret file. The avatar app draws the panels into
a cached surface only when the snapshot changes (or the minute turns), so the
per-frame cost is one blit.

  python3 cypher_panels.py --render out.png [--snapshot dash.json] [--size 1280x720] [--now EPOCH]
      one frame (avatar + panels) to a PNG without GTK, for tests and previews
"""
import json, os, re, sys, time
import cairo

E = os.environ.get
HOME = os.path.expanduser("~")
STATE = E("CYPHER_STATE_DIR", os.path.join(E("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "cypher"))
CFG = E("CYPHER_CONFIG_DIR", os.path.join(E("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "cypher"))
SNAP = os.path.join(STATE, "dash.json")
HIDDEN = os.path.join(CFG, "panels-hidden")
STALE_S = 180
COL_W, MARGIN = 270, 14          # column width and edge margin at 1280x720

# palette (design page): background, magenta, cyan, acid green
BG = (0x0A / 255, 0x0A / 255, 0x12 / 255)
MAG = (1.0, 0x2A / 255, 0x6D / 255)
CYAN = (0x05 / 255, 0xD9 / 255, 0xE8 / 255)
ACID = (0x39 / 255, 1.0, 0x14 / 255)
DIM = (0.50, 0.53, 0.66)
TXT = (0.88, 0.90, 0.96)
AMBER = (1.0, 0.72, 0.18)
FONT = E("CYPHER_DASH_FONT", "monospace")
KIND_COLOR = {"thought": CYAN, "zack": ACID, "talk": ACID, "phone": MAG, "note": CYAN, "found": AMBER, "refused": MAG,
              "ask": AMBER, "sleep": DIM, "camera": DIM, "color": CYAN, "event": DIM}
BADGE_COLOR = {"ALPHA": CYAN, "LOCAL": ACID, "GROK": MAG, "NONE": DIM}
DRIVE_COLOR = {"energy": ACID, "curiosity": CYAN, "social": MAG, "boredom": AMBER, "focus": CYAN}

# ---- the same scrubbing as cypherd.dash_text, again here (never trust one layer) ----
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_SCRUB = [
    (re.compile(r"\b(?:token|api[_ -]?key|password|passwd|secret|topic)\s*[:=]\s*\S+", re.I), "[redacted]"),
    (re.compile(r"\b(?:https?|rtsp|rtsps|wss?|mqtt)://\S+|www\.\S+", re.I), "[link]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b(?:light|switch|camera|lock|cover|alarm_control_panel|binary_sensor|sensor|automation|script|scene|"
                r"input_\w+|media_player|climate|fan|siren|button|select|number)\.[a-z0-9_]+", re.I), "[device]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "[addr]"),
    (re.compile(r"\b(?:cypher-[A-Za-z0-9_-]{6,}|xai-[A-Za-z0-9_-]{6,}|Bearer\s+\S+|eyJ[\w-]{8,}\S*|[A-Za-z0-9_+/=-]{20,})"), "[redacted]"),
]
_NAME_RE = re.compile(r"^[A-Z][a-z]{1,15}$")

def safe(t, n=140):
    t = _CTRL.sub(" ", t if isinstance(t, str) else ("" if t is None else str(t)))
    for rx, sub in _SCRUB:
        t = rx.sub(sub, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n - 1] + "\u2026"

def load_snapshot(path=SNAP):
    try:
        with open(path) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else None
    except (OSError, ValueError):
        return None

def hidden():
    return os.path.exists(HIDDEN)

def snapshot_mtime(path=SNAP):
    try: return os.stat(path).st_mtime
    except OSError: return 0

# ---- drawing helpers ----
def font(cr, size, bold=False):
    cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)

def fit(cr, text, width):
    if cr.text_extents(text).x_advance <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cr.text_extents(text[:mid] + "\u2026").x_advance <= width: lo = mid
        else: hi = mid - 1
    return text[:lo].rstrip() + "\u2026"

def wrap(cr, text, width, max_lines):
    lines, cur = [], ""
    for w in text.split(" "):
        t = (cur + " " + w).strip()
        if cr.text_extents(t).x_advance <= width or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != text:
        lines[-1] = fit(cr, lines[-1] + " \u2026", width)
    return [fit(cr, l, width) for l in lines]

def text(cr, x, y, s, color, size, bold=False, width=None, glow=False, alpha=1.0):
    font(cr, size, bold)
    if width: s = fit(cr, s, width)
    if glow:
        cr.set_source_rgba(*color, 0.25 * alpha)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cr.move_to(x + dx, y + dy); cr.show_text(s)
    cr.set_source_rgba(*color, alpha); cr.move_to(x, y); cr.show_text(s)
    return cr.text_extents(s).x_advance

def panel(cr, x, y, w, h, title, color):
    """A cut-corner neon frame with a title tab, on a dark translucent fill."""
    c = 10
    cr.new_path()
    cr.move_to(x + c, y); cr.line_to(x + w, y); cr.line_to(x + w, y + h - c)
    cr.line_to(x + w - c, y + h); cr.line_to(x, y + h); cr.line_to(x, y + c); cr.close_path()
    cr.set_source_rgba(*BG, 0.78); cr.fill_preserve()
    cr.set_source_rgba(*color, 0.07); cr.fill_preserve()
    cr.set_source_rgba(*color, 0.8); cr.set_line_width(1.3); cr.stroke()
    cr.set_source_rgba(0, 0, 0, 0.18)                       # scanlines, inside the frame only
    for sy in range(int(y) + 2, int(y + h) - 2, 3):
        cr.rectangle(x + 2, sy, w - 4, 1)
    cr.fill()
    font(cr, 11, True)
    tw = cr.text_extents(title).x_advance
    cr.set_source_rgb(*color); cr.rectangle(x + 14, y - 8, tw + 12, 15); cr.fill()
    cr.set_source_rgb(*BG); cr.move_to(x + 20, y + 4); cr.show_text(title)

def badge(cr, x, y, label, color, size=12):
    font(cr, size, True)
    tw = cr.text_extents(label).x_advance
    cr.set_source_rgba(*BG, 0.8); cr.rectangle(x, y, tw + 14, size + 10); cr.fill()
    cr.set_source_rgba(*color, 0.18); cr.rectangle(x, y, tw + 14, size + 10); cr.fill()
    cr.set_source_rgb(*color); cr.set_line_width(1.2); cr.rectangle(x + 0.5, y + 0.5, tw + 13, size + 9); cr.stroke()
    cr.move_to(x + 7, y + size + 4); cr.show_text(label)
    return tw + 14

# ---- the two columns ----
def render_panels(cr, w, h, snap, now=None):
    """Draw the left and right columns on a transparent surface of size w x h."""
    now = now or time.time()
    k = h / 720.0
    s = snap or {}
    stale = not snap or now - float(s.get("epoch") or 0) > STALE_S

    # ---------------- left column ----------------
    cr.save(); cr.translate(MARGIN * k, 0); cr.scale(k, k); W = COL_W
    text(cr, 2, 104, "CYPHER", CYAN, 28, True)
    text(cr, 0, 102, "CYPHER", MAG, 28, True, glow=True)
    brain = safe(s.get("brain"), 6) or "NONE"
    if brain not in BADGE_COLOR: brain = "NONE"
    font(cr, 12, True); bw = cr.text_extents(brain).x_advance + 14
    badge(cr, W - bw, 84, brain, BADGE_COLOR[brain])

    panel(cr, 0, 124, W, 206, "MOOD / DRIVES", CYAN)
    md = s.get("mood") or {}
    text(cr, 14, 160, safe(md.get("label"), 16).upper() or "--", ACID, 26, True, width=W - 28, glow=True)
    dr = s.get("drives") or {}
    for i, key in enumerate(("energy", "curiosity", "social", "boredom", "focus")):
        y = 178 + i * 29
        val = dr.get(key); val = max(0.0, min(1.0, float(val))) if isinstance(val, (int, float)) else 0.0
        text(cr, 14, y + 11, key.upper(), TXT, 10.5, True)
        bx, bw2, segs = 98, 126, 14
        cr.set_source_rgba(*DRIVE_COLOR[key], 0.16); cr.rectangle(bx, y, bw2, 13); cr.fill()
        for j in range(int(round(val * segs))):
            cr.set_source_rgb(*DRIVE_COLOR[key]); cr.rectangle(bx + j * (bw2 / segs) + 1, y + 2, bw2 / segs - 2, 9); cr.fill()
        text(cr, bx + bw2 + 6, y + 11, "%.2f" % val, DIM, 10.5)

    panel(cr, 0, 346, W, 106, "NOW", MAG)
    act = "cypherd is quiet" if stale else (safe(s.get("activity"), 60) or "watching")
    font(cr, 15, True)
    y = 372
    for line in wrap(cr, act, W - 28, 1):
        text(cr, 14, y, line, MAG if stale else TXT, 15, True); y += 19
    reason = safe(s.get("reason"), 140)
    font(cr, 11.5)
    for line in wrap(cr, ("why: " + reason) if reason else "", W - 28, 2):
        text(cr, 14, y, line, DIM, 11.5); y += 15
    flags = []
    if s.get("quiet"): flags.append("QUIET")
    for f in s.get("switches") or []:
        if f in ("muted", "KILL"): flags.append({"muted": "MUTED", "KILL": "KILLED"}[f])
    if not s.get("active", True) and not stale: flags.append("STANDBY")
    if stale: flags.append("NO SIGNAL")
    fx = 14
    for f in flags[:3]:
        fx += badge(cr, fx, 424, f, MAG if f == "NO SIGNAL" else AMBER, 10) + 6

    panel(cr, 0, 468, W, 100, "CAMERAS (read-only)", AMBER)
    cams = [c for c in s.get("camera") or [] if isinstance(c, dict)][-3:]
    if not cams: text(cr, 14, 496, "nothing new", DIM, 12)
    for i, c in enumerate(reversed(cams)):
        names = [n for n in c.get("names") or [] if isinstance(n, str) and _NAME_RE.match(n)][:3]
        line = "%s %s %s%s" % (safe(c.get("time"), 5), safe(c.get("camera"), 16), safe(c.get("kind"), 16).replace("_", " "),
                               (" (" + ", ".join(names) + ")") if names else "")
        text(cr, 14, 496 + i * 22, line, TXT, 12, width=W - 28)

    panel(cr, 0, 584, W, 120, "ZACK / PHONE", ACID)
    y = 610
    font(cr, 12)
    for t, msg in [m for m in s.get("zack") or [] if isinstance(m, list) and len(m) == 2][-2:]:
        for line in wrap(cr, "%s %s" % (safe(t, 8), safe(msg, 140)), W - 28, 2):
            text(cr, 14, y, line, TXT, 12); y += 16
        y += 4
    reqs = list(dict.fromkeys(safe(r, 40) for r in s.get("requests") or []))[-2:]
    if reqs and y < 690:
        text(cr, 14, min(y, 690), "waiting on you: " + ", ".join(reqs), AMBER, 12, width=W - 28); y += 18
    if y == 610:
        text(cr, 14, y, "no replies yet", DIM, 12)
        text(cr, 14, y + 18, "(messages only, never approvals)", DIM, 11)
    cr.restore()

    # ---------------- right column ----------------
    cr.save(); cr.translate(w - (MARGIN + COL_W) * k, 0); cr.scale(k, k); W = COL_W
    clock = time.strftime("%a %-I:%M %p", time.localtime(now))
    font(cr, 17, True)
    text(cr, W - cr.text_extents(clock).x_advance, 104, clock, TXT, 17, True)
    tick = "TICK %s" % safe(str(s.get("tick", 0)), 8)
    text(cr, 0, 103, tick, DIM, 11)

    panel(cr, 0, 124, W, 346, "JOURNAL", CYAN)
    rows = [r for r in s.get("journal") or [] if isinstance(r, list) and len(r) == 3][-6:]
    if not rows: text(cr, 14, 156, "nothing journaled yet", DIM, 12)
    y = 150
    for hm, kind, t in reversed(rows):            # newest first
        kind = safe(kind, 10); col = KIND_COLOR.get(kind, DIM)
        cr.set_source_rgb(*col); cr.rectangle(14, y - 9, 3, 11); cr.fill()
        text(cr, 22, y, "%s  %s" % (safe(hm, 5), kind.upper()[:9]), col, 10.5, True)
        font(cr, 12.5); y += 16
        for line in wrap(cr, safe(t, 160), W - 30, 2):
            text(cr, 22, y, line, TXT, 12.5); y += 16
        y += 8
        if y > 452: break

    panel(cr, 0, 486, W, 218, "ACTIONS", MAG)
    acts = [safe(a, 70) for a in (s.get("actions") or [])][-7:]
    if not acts: text(cr, 14, 514, "none yet", DIM, 12)
    for i, a in enumerate(reversed(acts)):
        refused = "(refused" in a
        if refused:
            a = a.replace(" (refused: ", ": ", 1).rstrip(")")
        text(cr, 14, 514 + i * 26, ("\u2717 " if refused else "\u203a ") + a, MAG if refused else TXT, 12, width=W - 26)
    cr.restore()

def bar_width(w, h):
    """How wide the avatar's text bar may be so it never runs under a column."""
    k = h / 720.0
    return int(max(360, w - 2 * (MARGIN + COL_W + 18) * k))

AVATAR_H = .55   # avatar.py's default body height (fraction of the window height); width is 1.9x that

def avatar_h(w, h):
    """Body height for the avatar so it sits between the two columns instead of under them."""
    k = h / 720.0
    free = w - 2 * (MARGIN + COL_W + 16) * k
    return max(.3, min(AVATAR_H, free / (1.9 * h)))

class Cache:
    """Panels drawn once per snapshot change into an ARGB surface; the avatar blits it each frame."""
    def __init__(self):
        self.surf, self.key = None, None
    def surface(self, w, h, now=None, key=None):
        now = now or time.time()
        key = (w, h) + tuple(key if key is not None else (snapshot_mtime(), int(now // 60)))
        if self.surf is None or key != self.key:
            self.surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
            cr = cairo.Context(self.surf)
            render_panels(cr, w, h, load_snapshot(), now)
            self.key = key
        return self.surf

def render_png(path, snap, size=(1280, 720), now=None, avatar=True):
    """Avatar (cairo renderer, if the avatar module is importable) + panels, to a PNG."""
    W, H = size
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0, 0, 0); cr.paint()
    if avatar:
        for d in (E("NOVA_DIR"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nova"), "/usr/share/grokbot/nova"):
            if d and os.path.exists(os.path.join(d, "avatar.py")) and d not in sys.path:
                sys.path.insert(0, d)
        try:
            from avatar import Avatar
            import avatar_shapes as AS
            av = Avatar(style=AS.load(), layout={"h": avatar_h(W, H)}); av.tick(0.05); av.draw(cr, W, H)
        except Exception as e:                    # the preview still shows the panels
            print("avatar not drawn:", type(e).__name__, e, file=sys.stderr)
    render_panels(cr, W, H, snap, now)
    surf.write_to_png(path)

def main(argv):
    if "--render" in argv:
        out = argv[argv.index("--render") + 1]
        snap_path = argv[argv.index("--snapshot") + 1] if "--snapshot" in argv else SNAP
        size = (1280, 720)
        if "--size" in argv:
            a, b = argv[argv.index("--size") + 1].split("x"); size = (int(a), int(b))
        now = float(argv[argv.index("--now") + 1]) if "--now" in argv else None
        render_png(out, load_snapshot(snap_path), size, now, avatar="--no-avatar" not in argv)
        return 0
    print(__doc__.strip()); return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
