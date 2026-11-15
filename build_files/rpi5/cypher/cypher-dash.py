#!/usr/bin/env python3
"""cypher-dash - Cypher's cyberpunk dashboard on the deck's own screen (phase 4).

GTK3 + pycairo (the same stack as Nova's native shell), app_id "cypher-dash", on its
own sway workspace (9). Super+C shows it and goes back; a tap or Escape goes back.

It only reads ~/.local/state/cypher/dash.json, a display-only snapshot cypherd writes
every loop with every string already scrubbed (cypherd.dash_text). It never opens
the ntfy topic, the proxy token, the xAI key, Home Assistant or camera settings, and
scrubs again before drawing anything (defense in depth). Redraws at most every
2 s, only when the snapshot changed (plus once a minute for the clock), so it
costs next to nothing on the Pi 5. When its workspace is hidden, GTK does not draw.

  cypher-dash.py                       the window
  cypher-dash.py --render out.png [--snapshot dash.json] [--size 1280x720]
                                       draw one frame to a PNG (tests, previews; no GTK)
"""
import json, math, os, re, subprocess, sys, time
import cairo

E = os.environ.get
HOME = os.path.expanduser("~")
STATE = E("CYPHER_STATE_DIR", os.path.join(E("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "cypher"))
SNAP = os.path.join(STATE, "dash.json")
TOGGLE = E("CYPHER_DASH_TOGGLE", "/usr/local/bin/grokbot-cypher-dash")
STALE_S = 180
os.environ.setdefault("TZ", "America/New_York"); time.tzset()

# palette (design page): background, magenta, cyan, acid green
BG = (0x0A / 255, 0x0A / 255, 0x12 / 255)
MAG = (1.0, 0x2A / 255, 0x6D / 255)
CYAN = (0x05 / 255, 0xD9 / 255, 0xE8 / 255)
ACID = (0x39 / 255, 1.0, 0x14 / 255)
DIM = (0.42, 0.45, 0.58)
TXT = (0.86, 0.88, 0.95)
AMBER = (1.0, 0.72, 0.18)
FONT = E("CYPHER_DASH_FONT", "monospace")
KIND_COLOR = {"thought": CYAN, "zack": ACID, "phone": MAG, "note": CYAN, "found": AMBER, "refused": MAG,
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
    words, lines, cur = text.split(" "), [], ""
    for w in words:
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

def text(cr, x, y, s, color, size, bold=False, width=None, glow=False):
    font(cr, size, bold)
    if width: s = fit(cr, s, width)
    if glow:
        cr.set_source_rgba(*color, 0.25)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cr.move_to(x + dx, y + dy); cr.show_text(s)
    cr.set_source_rgb(*color); cr.move_to(x, y); cr.show_text(s)
    return cr.text_extents(s).x_advance

def panel(cr, x, y, w, h, title, color):
    """A cut-corner neon frame with a title tab."""
    c = 12
    cr.new_path()
    cr.move_to(x + c, y); cr.line_to(x + w, y); cr.line_to(x + w, y + h - c)
    cr.line_to(x + w - c, y + h); cr.line_to(x, y + h); cr.line_to(x, y + c); cr.close_path()
    cr.set_source_rgba(*color, 0.06); cr.fill_preserve()
    cr.set_source_rgba(*color, 0.75); cr.set_line_width(1.5); cr.stroke()
    font(cr, 13, True)
    tw = cr.text_extents(title).x_advance
    cr.set_source_rgb(*color); cr.rectangle(x + 18, y - 9, tw + 14, 18); cr.fill()
    cr.set_source_rgb(*BG); cr.move_to(x + 25, y + 5); cr.show_text(title)

def background(cr, w, h):
    cr.set_source_rgb(*BG); cr.paint()
    cr.set_line_width(1)
    cr.set_source_rgba(*CYAN, 0.035)
    for gx in range(0, w, 40):
        cr.move_to(gx + 0.5, 0); cr.line_to(gx + 0.5, h)
    for gy in range(0, h, 40):
        cr.move_to(0, gy + 0.5); cr.line_to(w, gy + 0.5)
    cr.stroke()
    cr.set_source_rgba(0, 0, 0, 0.22)                 # scanlines
    for sy in range(0, h, 3):
        cr.rectangle(0, sy, w, 1)
    cr.fill()

def badge(cr, x, y, label, color):
    font(cr, 16, True)
    tw = cr.text_extents(label).x_advance
    cr.set_source_rgba(*color, 0.15); cr.rectangle(x, y, tw + 20, 28); cr.fill()
    cr.set_source_rgb(*color); cr.set_line_width(1.5); cr.rectangle(x + 0.5, y + 0.5, tw + 19, 27); cr.stroke()
    cr.move_to(x + 10, y + 20); cr.show_text(label)
    return tw + 20

# ---- one frame ----
def render(cr, w, h, snap, now=None):
    now = now or time.time()
    sx, sy = w / 1280.0, h / 720.0
    cr.save(); cr.scale(sx, sy); W, H = 1280, 720
    background(cr, W, H)
    s = snap or {}
    stale = not snap or now - float(s.get("epoch") or 0) > STALE_S

    # header
    text(cr, 32, 58, "CYPHER", CYAN, 44, True)                       # glitch offset
    text(cr, 29, 56, "CYPHER", MAG, 44, True, glow=True)
    text(cr, 250, 56, "// netrunner in the deck", DIM, 16)
    x = W - 32
    clock = time.strftime("%a %-I:%M %p", time.localtime(now))
    font(cr, 22, True); x -= cr.text_extents(clock).x_advance
    text(cr, x, 52, clock, TXT, 22, True)
    brain = safe(s.get("brain"), 6) or "NONE"
    if brain not in BADGE_COLOR: brain = "NONE"
    font(cr, 16, True); x -= cr.text_extents(brain).x_advance + 20 + 18
    badge(cr, x, 31, brain, BADGE_COLOR[brain])
    tick = "TICK %s" % safe(str(s.get("tick", 0)), 8)
    font(cr, 14); x -= cr.text_extents(tick).x_advance + 16
    text(cr, x, 50, tick, DIM, 14)
    cr.set_source_rgba(*MAG, 0.8); cr.set_line_width(2); cr.move_to(28, 76); cr.line_to(W - 28, 76); cr.stroke()
    cr.set_source_rgba(*CYAN, 0.6); cr.set_line_width(1); cr.move_to(28, 80); cr.line_to(W * 0.45, 80); cr.stroke()

    # left: mood + drives
    panel(cr, 28, 104, 392, 300, "MOOD / DRIVES", CYAN)
    md = s.get("mood") or {}
    label = safe(md.get("label"), 16).upper() or "--"
    text(cr, 48, 160, label, ACID, 38, True, width=350, glow=True)
    v, a = md.get("valence"), md.get("arousal")
    if isinstance(v, (int, float)) and isinstance(a, (int, float)):
        text(cr, 50, 186, "valence %+.2f   arousal %.2f" % (v, a), DIM, 14)
    dr = s.get("drives") or {}
    for i, k in enumerate(("energy", "curiosity", "social", "boredom", "focus")):
        y = 216 + i * 36
        val = dr.get(k); val = max(0.0, min(1.0, float(val))) if isinstance(val, (int, float)) else 0.0
        text(cr, 48, y + 14, k.upper(), TXT, 13, True)
        bx, bw = 160, 200
        cr.set_source_rgba(*DRIVE_COLOR[k], 0.15); cr.rectangle(bx, y, bw, 16); cr.fill()
        segs = 20
        for j in range(int(round(val * segs))):
            cr.set_source_rgb(*DRIVE_COLOR[k]); cr.rectangle(bx + j * (bw / segs) + 1, y + 2, bw / segs - 2, 12); cr.fill()
        text(cr, bx + bw + 10, y + 14, "%.2f" % val, DIM, 13)

    # left: activity
    panel(cr, 28, 430, 392, 150, "NOW", MAG)
    act = "cypherd is quiet" if stale else (safe(s.get("activity"), 60) or "watching")
    text(cr, 48, 470, act, MAG if stale else TXT, 22, True, width=352)
    font(cr, 14)
    reason = safe(s.get("reason"), 140)
    y = 498
    for line in wrap(cr, ("why: " + reason) if reason else "", 352, 3):
        text(cr, 48, y, line, DIM, 14); y += 20
    flags = []
    if s.get("quiet"): flags.append("QUIET HOURS")
    for f in s.get("switches") or []:
        if f in ("muted", "KILL"): flags.append({"muted": "MUTED", "KILL": "KILLED"}[f])
    if not s.get("active", True) and not stale: flags.append("STANDBY")
    if stale: flags.append("NO SIGNAL")
    fx = 48
    for f in flags:
        fx += badge(cr, fx, 548, f, AMBER if f != "NO SIGNAL" else MAG) + 8
        if fx > 380: break

    # right: journal
    panel(cr, 448, 104, 804, 300, "JOURNAL", CYAN)
    rows = [r for r in s.get("journal") or [] if isinstance(r, list) and len(r) == 3][-8:]
    if not rows:
        text(cr, 470, 150, "nothing journaled yet", DIM, 16)
    for i, (hm, kind, t) in enumerate(rows):
        y = 142 + i * 32
        kind = safe(kind, 10)
        col = KIND_COLOR.get(kind, DIM)
        text(cr, 470, y, safe(hm, 5), DIM, 14)
        cr.set_source_rgb(*col); cr.rectangle(526, y - 12, 4, 15); cr.fill()
        text(cr, 540, y, fit_kind(kind), col, 13, True)
        text(cr, 640, y, safe(t, 140), TXT, 15, width=596)

    # bottom row: actions / cameras / phone
    panel(cr, 448, 430, 300, 260, "ACTIONS", MAG)
    acts = [safe(a, 60) for a in (s.get("actions") or [])][-7:]
    for i, a in enumerate(reversed(acts)):
        y = 466 + i * 30
        refused = "(refused" in a
        if refused:
            a = a.replace(" (refused: ", ": ", 1).rstrip(")")
        text(cr, 466, y, ("\u2717 " if refused else "\u203a ") + a, MAG if refused else TXT, 14, width=266)
    if not acts: text(cr, 466, 466, "none yet", DIM, 14)

    panel(cr, 768, 430, 484, 120, "CAMERAS (read-only)", AMBER)
    cams = [c for c in s.get("camera") or [] if isinstance(c, dict)][-3:]
    if not cams: text(cr, 786, 470, "nothing new", DIM, 14)
    for i, c in enumerate(reversed(cams)):
        names = [n for n in c.get("names") or [] if isinstance(n, str) and _NAME_RE.match(n)][:4]
        line = "%s  %s  %s%s" % (safe(c.get("time"), 5), safe(c.get("camera"), 20), safe(c.get("kind"), 20).replace("_", " "),
                                 ("  (" + ", ".join(names) + ")") if names else "")
        text(cr, 786, 466 + i * 26, line, TXT, 14, width=448)

    panel(cr, 768, 570, 484, 120, "ZACK / PHONE", ACID)
    y = 606
    for t, msg in [m for m in s.get("zack") or [] if isinstance(m, list) and len(m) == 2][-2:]:
        text(cr, 786, y, "%s  %s" % (safe(t, 8), safe(msg, 140)), TXT, 14, width=448); y += 24
    reqs = list(dict.fromkeys(safe(r, 40) for r in s.get("requests") or []))[-3:]
    if reqs:
        text(cr, 786, y, "waiting on you: account for " + ", ".join(reqs), AMBER, 14, width=448); y += 24
    if y == 606:
        text(cr, 786, y, "no replies yet (messages only, never approvals)", DIM, 14, width=448)

    # left bottom hint
    text(cr, 30, 690, "SUPER+C or tap: back   //   phase %s   host %s" % (safe(str(s.get("phase", "?")), 3),
                                                                     safe(s.get("host"), 8) or "?"), DIM, 13)
    cr.restore()

def fit_kind(k):
    return k.upper()[:9]

def render_png(path, snap, size=(1280, 720), now=None):
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, *size)
    cr = cairo.Context(surf)
    render(cr, size[0], size[1], snap, now)
    surf.write_to_png(path)

# ---- the window ----
def run_window():
    import gi
    gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
    from gi.repository import GLib
    GLib.set_prgname("cypher-dash")          # -> Wayland app_id; sway puts it on workspace 9
    from gi.repository import Gtk, Gdk
    state = {"snap": load_snapshot(), "mtime": 0, "minute": None}

    def go_back(*_):
        try: subprocess.Popen([TOGGLE, "back"])
        except OSError: pass
        return True

    win = Gtk.Window(title="Cypher")
    win.set_decorated(False)
    win.set_default_size(1280, 720)
    area = Gtk.DrawingArea()
    area.connect("draw", lambda w, cr: render(cr, w.get_allocated_width(), w.get_allocated_height(), state["snap"]))
    win.add(area)
    win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
    win.connect("button-press-event", go_back)
    win.connect("touch-event", lambda w, ev: go_back() if ev.type == Gdk.EventType.TOUCH_BEGIN else False)
    win.connect("key-press-event", lambda w, ev: go_back() if ev.keyval == Gdk.KEY_Escape else False)
    win.connect("destroy", Gtk.main_quit)

    def poll():
        try: m = os.stat(SNAP).st_mtime
        except OSError: m = 0
        minute = int(time.time() // 60)
        if m != state["mtime"] or minute != state["minute"]:
            state["mtime"], state["minute"] = m, minute
            state["snap"] = load_snapshot()
            area.queue_draw()
        return True
    GLib.timeout_add_seconds(2, poll)
    win.show_all()
    Gtk.main()

def main(argv):
    if "--render" in argv:
        out = argv[argv.index("--render") + 1]
        snap_path = argv[argv.index("--snapshot") + 1] if "--snapshot" in argv else SNAP
        size = (1280, 720)
        if "--size" in argv:
            a, b = argv[argv.index("--size") + 1].split("x"); size = (int(a), int(b))
        now = float(argv[argv.index("--now") + 1]) if "--now" in argv else None
        render_png(out, load_snapshot(snap_path), size, now)
        return 0
    run_window()
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
