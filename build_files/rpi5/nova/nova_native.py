#!/usr/bin/env python3
"""Cypher's face for grokbotos (GTK3 + pycairo): the avatar, the text bar and voice,
and Cypher's HUD panels around the avatar (cypher_panels: mood, drives, brain,
activity, journal, actions, camera line, phone replies, account requests; Super+C
hides/shows them). Talking here is talking to Cypher (novad -> cypher_link).
Client of novad (http://127.0.0.1:8765). The internal names stay (nova_native.py,
Wayland app_id "nova-shell") so the sway rules, the Super toggle and novad's focus
watcher keep working. No on-screen keyboard by design."""
import argparse, json, os, socket, sys, threading, time, urllib.request, urllib.error
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import GLib
GLib.set_prgname("nova-shell")          # -> xdg app_id "nova-shell" on Wayland, WM_CLASS on X
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, Pango
import cairo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from avatar import Avatar
import avatar_shapes as AS
for _d in (os.environ.get("CYPHER_LIB"), "/usr/share/grokbot/cypher",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cypher")):
    if _d and os.path.exists(os.path.join(_d, "cypher_panels.py")):
        sys.path.insert(0, _d); break
try:
    import cypher_panels as CP              # Cypher's HUD; the avatar works without it
except Exception as _e:
    CP = None; print("cypher panels unavailable:", type(_e).__name__, file=sys.stderr, flush=True)
try:
    import cypher_journal as CJ             # build 14: readable entries for the journal viewer (read-only)
except Exception as _e:
    CJ = None; print("cypher journal unavailable:", type(_e).__name__, file=sys.stderr, flush=True)

NET_ERR = "I can't reach my voice service right now."
# Build 14: power_off's Confirm click goes to novad over this owner-only unix socket (HTTP yes is refused).
CONFIRM_SOCK = os.environ.get("NOVA_CONFIRM_SOCK") or os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "nova", "confirm.sock")
CSS = b"""
window, .nova { background: #000; }
#reply { color: #d1fae5; font-size: 24px; }
#reply.err { color: #fcd34d; }
#reply.q { color: #fff; font-weight: 600; background: rgba(0,0,0,.72); border-radius: 18px; padding: 8px 18px; }
#echo { color: #fff; font-size: 18px; }
#vnote { color: rgba(255,255,255,.55); font-size: 15px; }
#inbox { background: rgba(20,24,22,.85); border: 1px solid rgba(110,231,183,.18); border-radius: 28px; }
#inbox:focus-within { border-color: rgba(110,231,183,.45); }
textview#in, textview#in text { font-size: 20px; color: #fff; background: transparent; background-image: none; caret-color: #fff; }
#inph { color: rgba(255,255,255,.4); font-size: 20px; }
button.cf { font-size: 22px; min-width: 150px; padding: 14px 26px; border-radius: 28px; background-image: none; box-shadow: none; text-shadow: none; }
button#yes { background: #14C370; color: #04140b; border: 0; font-weight: 700; }
button#no { background: rgba(20,24,22,.7); color: #fff; border: 1px solid rgba(255,255,255,.25); }
button.cf label.small { font-size: 13px; font-weight: 400; opacity: .6; }
button.vb { min-width: 42px; min-height: 42px; padding: 0; border-radius: 21px; border: 1px solid rgba(110,231,183,.18);
  background: rgba(20,24,22,.7); background-image: none; color: #d1fae5; box-shadow: none; }
button.vb.off { opacity: .35; }
button.vb.on { background: #14C370; color: #04140b; border-color: #14C370; }
button#look { min-width: 52px; min-height: 52px; padding: 0; border-radius: 26px; border: 1px solid rgba(255,255,255,.14);
  background: rgba(20,24,22,.55); background-image: none; box-shadow: none; opacity: .7; }
button#pad { min-width: 52px; min-height: 52px; padding: 0 10px; border-radius: 26px; border: 1px solid rgba(255,255,255,.14);
  background: rgba(20,24,22,.55); background-image: none; box-shadow: none; opacity: .7; color: #d1fae5; font-size: 15px; font-weight: 700; }
#picker { background: rgba(0,0,0,.94); }
#jview { background: rgba(0,0,0,.55); }
#jcard { background: rgba(6,12,14,.95); border: 1px solid rgba(34,211,238,.45); border-radius: 14px; padding: 10px 14px; }
#jcard label.jttl { color: #22d3ee; font-size: 18px; font-weight: 700; }
#jcard label.jhead { color: #22d3ee; font-size: 14px; font-weight: 700; }
#jcard label.jwhat { color: #fff; font-size: 17px; }
#jcard label.jwhy { color: rgba(255,255,255,.7); font-size: 15px; }
#jcard label.jres { color: #fcd34d; font-size: 15px; }
#jcard label.jdim { color: rgba(255,255,255,.45); font-size: 13px; }
#jcard button#jclose { font-size: 15px; padding: 4px 14px; border-radius: 16px; background: rgba(255,255,255,.1); background-image: none;
  color: #fff; border: 1px solid rgba(255,255,255,.25); box-shadow: none; text-shadow: none; }
#picker label.ttl { color: #fff; font-size: 26px; font-weight: 700; }
#picker label.sub { color: rgba(255,255,255,.55); font-size: 16px; }
#picker button.pick { padding: 0; border: 0; border-radius: 22px; background: transparent; background-image: none; box-shadow: none; }
#picker button.pick:hover, #picker button.pick:active { background: rgba(255,255,255,.06); }
#picker button#done { font-size: 20px; min-width: 160px; padding: 12px 26px; border-radius: 26px; background: rgba(255,255,255,.12);
  background-image: none; color: #fff; border: 1px solid rgba(255,255,255,.25); box-shadow: none; text-shadow: none; }
"""

class ChatInput:
    """Build 14: the text bar wraps. A multi-line TextView (word wrap, up to MAX_LINES tall, then it scrolls)
    that grows upward from the bottom bar instead of running sideways under the HUD panels. Enter sends,
    Shift+Enter is a new line. Same small API the app used on the old Gtk.Entry."""
    MAX_LINES = 4
    LINE_PX = 28
    def __init__(self, on_enter, placeholder="Ask Cypher…"):
        self.on_enter = on_enter
        tv = self.tv = Gtk.TextView(name="in", wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        tv.set_input_hints(Gtk.InputHints.INHIBIT_OSK)   # never pop an on-screen keyboard
        tv.set_left_margin(22); tv.set_right_margin(110); tv.set_top_margin(14); tv.set_bottom_margin(14)
        self.buf = tv.get_buffer()
        sw = self.sw = Gtk.ScrolledWindow(name="inbox")
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.max_h = self.MAX_LINES * self.LINE_PX + 28; self.fit_src = 0
        sw.add(tv)
        self.ph = Gtk.Label(name="inph", label=placeholder, halign=Gtk.Align.START, valign=Gtk.Align.CENTER, margin_start=24)
        self.widget = Gtk.Overlay(); self.widget.add(sw); self.widget.add_overlay(self.ph)
        self.widget.set_overlay_pass_through(self.ph, True)
        self.buf.connect("changed", lambda *_: (self.ph.set_visible(not self.get_text()), self._queue_fit()))
        tv.connect("size-allocate", lambda *_: self._queue_fit())
        tv.connect("key-press-event", self._key)
    def _queue_fit(self):
        if not self.fit_src: self.fit_src = GLib.idle_add(self._fit)
    def _fit(self):
        """Grow upward with the wrapped text, up to MAX_LINES; past that the box scrolls."""
        self.fit_src = 0
        y, h = self.tv.get_line_yrange(self.buf.get_end_iter())
        want = max(self.LINE_PX, y + h) + self.tv.get_top_margin() + self.tv.get_bottom_margin()
        want = min(self.max_h, want)
        if want != self.sw.get_min_content_height():
            self.sw.set_min_content_height(want)
        return False
    def height(self): return self.sw.get_min_content_height()
    def _key(self, w, e):
        if Gdk.keyval_name(e.keyval) in ("Return", "KP_Enter") and not (e.state & Gdk.ModifierType.SHIFT_MASK):
            self.on_enter(self); return True
        return False
    def get_text(self):
        return self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), False)
    def set_text(self, t): self.buf.set_text(t or "")
    def grab_focus(self): self.tv.grab_focus()
    def grab_focus_without_selecting(self): self.tv.grab_focus()
    def has_focus(self): return self.tv.has_focus()

def confirm_click(pid, yes, path=None, timeout=10):
    """Send an on-screen Confirm/Cancel click to novad's owner-only socket; returns novad's JSON answer."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout)
    try:
        s.connect(path or CONFIRM_SOCK)
        s.sendall((json.dumps({"id": pid, "yes": bool(yes), "via": "click"}) + "\n").encode())
        return json.loads(s.makefile("rb").readline() or b"{}")
    finally:
        s.close()

def column(W, H, panels):
    """(x, width) of the centre text column: cypher_panels.text_column when the HUD is up."""
    if CP is not None:
        return CP.text_column(W, H, panels)
    bw = max(160, min(720, int(W * .8)))
    return (W - bw) // 2, bw

class Fader:
    """Opacity tween for a widget (the CSS transitions in shell.html)."""
    def __init__(self, w, dur): self.w, self.dur, self.src, self.v = w, dur, 0, 0.0; w.set_opacity(0)
    def to(self, target, dur=None, instant=False):
        if self.src: GLib.source_remove(self.src); self.src = 0
        if instant or (dur if dur is not None else self.dur) <= 0:
            self.v = target; self.w.set_opacity(target); return
        a, d, t0 = self.v, dur if dur is not None else self.dur, time.monotonic()
        def step():
            p = min(1, (time.monotonic() - t0) / d); self.v = a + (target - a) * p; self.w.set_opacity(self.v)
            if p >= 1: self.src = 0; return False
            return True
        self.src = GLib.timeout_add(33, step)

def icon_draw(kind, get_state):
    def draw(w, cr):
        a = w.get_allocation(); c = w.get_style_context().get_color(w.get_state_flags())
        cr.translate((a.width - 20) / 2, (a.height - 20) / 2); cr.scale(20 / 24, 20 / 24)
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha); cr.set_line_width(2)
        cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
        if kind == "mic":
            cr.arc(12, 6, 3, 3.1416, 0); cr.line_to(15, 11); cr.arc(12, 11, 3, 0, 3.1416); cr.close_path(); cr.stroke()
            cr.arc_negative(12, 11, 7, 3.1416, 0); cr.stroke(); cr.move_to(12, 18); cr.line_to(12, 21); cr.stroke()
        else:
            cr.move_to(11, 5); cr.line_to(6, 9); cr.line_to(3, 9); cr.line_to(3, 15); cr.line_to(6, 15); cr.line_to(11, 19); cr.close_path(); cr.stroke()
            if get_state():
                cr.move_to(16, 9); cr.line_to(22, 15); cr.move_to(22, 9); cr.line_to(16, 15); cr.stroke()
            else:
                cr.arc(12, 12, 4.95, -0.785, 0.785); cr.stroke(); cr.arc(12, 12, 9.2, -0.785, 0.785); cr.stroke()
    return draw

def draw_shape_thumb(cr, W, H, shape, color, ring=False):
    """A still avatar (shape, color, eyes) for the picker grid."""
    s = min(W, H) * .27; cx, cy = W / 2, H / 2
    if shape == "capsule": s = min(W, H) * .5 / (2 * AS.CAPSULE_H) * .62
    if ring:
        cr.set_source_rgba(1, 1, 1, .9); cr.set_line_width(3)
        cr.arc(cx, cy, min(W, H) * .47, 0, 6.2832); cr.stroke()
    col = AS.color_rgb(color); pts = AS.outline(shape, 120)
    for i, (x, y, _) in enumerate(pts): (cr.line_to if i else cr.move_to)(cx + x * s, cy + y * s)
    cr.close_path(); cr.set_source_rgb(*col); cr.fill()
    dx, dy, es = AS.EYES.get(shape, (0, 0, 1))
    h0 = s / AS.SIZE if shape != "capsule" else s * 2 * AS.CAPSULE_H
    if shape != "capsule": es *= AS.EYE_K
    ew, eh, ex = h0 * .25 * es, h0 * .46 * es, h0 * .25 * es
    for sd in (-1, 1):
        x, y = cx + dx * s + sd * ex, cy + dy * s
        cr.new_path(); r = ew / 2
        cr.arc(x, y - eh / 2 + r, r, 3.1416, 0); cr.arc(x, y + eh / 2 - r, r, 0, 3.1416); cr.close_path()
        cr.set_source_rgb(0, 0, 0); cr.fill()

def draw_swatch(cr, W, H, color, ring=False):
    cx, cy, r = W / 2, H / 2, min(W, H) * .32
    if ring:
        cr.set_source_rgba(1, 1, 1, .95); cr.set_line_width(3); cr.arc(cx, cy, r + 7, 0, 6.2832); cr.stroke()
    cr.arc(cx, cy, r, 0, 6.2832); cr.set_source_rgb(*AS.color_rgb(color)); cr.fill_preserve()
    cr.set_source_rgba(1, 1, 1, .18); cr.set_line_width(1); cr.stroke()

class Nova:
    def __init__(self, a):
        self.a, self.base, self.live = a, a.base.rstrip("/"), not a.offline
        self.style = AS.load()
        if a.shape or a.color: self.style = AS.clean({**self.style, **({"shape": a.shape} if a.shape else {}), **({"color": a.color} if a.color else {})})
        self.av = Avatar(style=self.style); self.dpr = a.dpr
        if a.blink is not None: self.av.forceBlink = a.blink
        self.busy, self.pend, self.pendT, self.tms = False, None, 0, []
        self.V = dict(mic=False, speaker=False, muted=False, cap=30, rec=False, speaking=False, downAt=0, tap=False, capT=0, noteT=0)
        self.first_status = True; self.frames = 0
        prov = Gtk.CssProvider(); prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        s = Gtk.Settings.get_default(); s.set_property("gtk-application-prefer-dark-theme", True)
        w = self.win = Gtk.Window(title="Cypher"); w.get_style_context().add_class("nova")
        w.set_default_size(*a.size); w.connect("destroy", Gtk.main_quit)
        ov = Gtk.Overlay(); w.add(ov)
        if a.renderer == "gl":
            from glview import GLView, GLAvatar
            self.av = GLAvatar(style=self.style); self.da = GLView(self.av); self.redraw = self.da.queue_render
            if a.blink is not None: self.av.forceBlink = a.blink
        else:
            self.da = Gtk.DrawingArea(); self.da.connect("draw", self.on_draw); self.redraw = self.da.queue_draw
        ov.add(self.da)
        self.surf = None
        # Cypher's HUD around the avatar: drawn into a cache only when dash.json changes
        self.hud = None; self.hud_key = None; self.base_h = self.av.lay["h"]
        if CP is not None and not a.no_panels:
            self.hud_cache = CP.Cache(); self.hud = Gtk.DrawingArea()
            self.hud.connect("draw", self.on_hud_draw)
            ov.add_overlay(self.hud); ov.set_overlay_pass_through(self.hud, True)
        # bottom bar
        # build 14: the bar fills exactly the centre column (side margins set in on_size), and the reply, the
        # echo and the input all wrap inside it, so nothing runs under the HUD panels.
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.FILL, valign=Gtk.Align.END); self.bar = bar
        self.reply = Gtk.Label(name="reply", wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, justify=Gtk.Justification.CENTER,
                               halign=Gtk.Align.FILL, xalign=0.5, margin_bottom=12)
        self.echo = Gtk.Label(name="echo", wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, justify=Gtk.Justification.CENTER,
                              halign=Gtk.Align.FILL, xalign=0.5, margin_bottom=10)
        self.echo.set_size_request(-1, 22)
        self.fr, self.fe = Fader(self.reply, .8), Fader(self.echo, .4)
        self.cf = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, margin_bottom=14, no_show_all=True)
        self.cf_lbl = {}; self.pend_phys = False
        for nm, key, yes in (("Yes", "Enter", True), ("No", "Esc", False)):
            b = Gtk.Button(name=nm.lower()); b.get_style_context().add_class("cf"); b.set_can_focus(False)
            lab = Gtk.Label(label=nm); bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); bx.add(lab)
            sm = Gtk.Label(label=key); sm.get_style_context().add_class("small"); bx.add(sm); b.add(bx); bx.show_all()
            self.cf_lbl[yes] = (lab, sm, nm, key)
            b.connect("clicked", lambda _b, y=yes: self.answer(y, click=True)); b.show(); self.cf.add(b)
        row = Gtk.Overlay()
        self.inp = ChatInput(self.on_enter)
        row.add(self.inp.widget)
        self.inp.widget.connect("size-allocate", lambda *_: self._place_vnote())   # the hint sits above a grown bar
        vb = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.END, margin_end=8, margin_bottom=7)
        self.mute = self._vbtn("mute", lambda: self.V["muted"]); self.mic = self._vbtn("mic", None)
        self.mute.connect("clicked", lambda *_: self.toggle_mute())
        self.mic.connect("button-press-event", self.mic_down); self.mic.connect("button-release-event", self.mic_up)
        self.mic.connect("touch-event", self.mic_touch)
        vb.add(self.mute); vb.add(self.mic); row.add_overlay(vb)
        for x in (self.reply, self.echo, self.cf, row): bar.add(x)
        ov.add_overlay(bar)
        self.vnote = Gtk.Label(name="vnote", halign=Gtk.Align.CENTER, valign=Gtk.Align.END); self.fv = Fader(self.vnote, .6)
        ov.add_overlay(self.vnote); ov.set_overlay_pass_through(self.vnote, True)
        # look picker: a small button top-right opens a grid of shapes and a row of colors
        self.look = Gtk.Button(name="look", halign=Gtk.Align.END, valign=Gtk.Align.START, margin_top=16, margin_end=16)
        self.look.set_can_focus(False); self.look.set_tooltip_text("Change my look")
        ld = Gtk.DrawingArea(); ld.set_size_request(30, 30)
        ld.connect("draw", lambda w, cr: draw_shape_thumb(cr, w.get_allocated_width(), w.get_allocated_height(),
                                                         self.style["shape"], self.style["color"]) or False)
        self.look.add(ld); self.look_icon = ld
        self.look.connect("clicked", lambda *_: self.open_picker()); ov.add_overlay(self.look)
        # Onshape pad: a second corner button (top-left) opens cadpad.py (app_id nova-cadpad)
        self.pad = Gtk.Button(name="pad", label="CAD", halign=Gtk.Align.START, valign=Gtk.Align.START, margin_top=16, margin_start=16)
        self.pad.set_can_focus(False); self.pad.set_tooltip_text("Onshape pad")
        self.pad.connect("clicked", lambda *_: self.open_pad()); ov.add_overlay(self.pad)
        self.picker = self._build_picker(); ov.add_overlay(self.picker)
        self.jv = self._build_journal(); ov.add_overlay(self.jv)          # build 14: read-only journal viewer
        self.cfg_mtime = self._cfg_mtime(); GLib.timeout_add_seconds(2, self._watch_cfg)
        w.connect("size-allocate", self.on_size)
        w.connect("key-press-event", self.on_key); w.connect("key-release-event", self.on_key_up)
        w.show_all(); self.mute.hide(); self.mic.hide(); self.picker.hide(); self.jv.hide(); self._watch_hud()
        if a.renderer == "gl":
            print("renderer gl:", getattr(self.da, "info", None), "failed:", self.da.failed, file=sys.stderr, flush=True)
            if self.da.failed: os.execv(sys.executable, [sys.executable] + sys.argv + ["--renderer", "cairo"])
        if a.fullscreen: w.fullscreen()
        self.inp.grab_focus()
        self.last = time.monotonic(); self.next_due = 0
        self.da.add_tick_callback(self.on_tick)   # frame clock: paused by the compositor when hidden
        self.act = time.monotonic(); self.dozing = False
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        for sig in ("key-press-event", "button-press-event", "touch-event"): w.connect(sig, self.on_activity)
        w.connect("button-press-event", self.on_hud_tap)    # the HUD is pass-through: map a tap on its JOURNAL panel
        if getattr(a, "journal", False): self.open_journal()
        GLib.timeout_add_seconds(5, self.doze_check)
        if a.picker: self.open_picker()
        if a.state: self.av.set_state(a.state)
        if a.sim: self.av.simulate(a.sim)
        if a.confirm:
            self.ask_confirm({"id": "demo", "text": a.confirm, "ttl": 3600}); self.set_echo(a.q or "")
        if a.reply:
            self.set_echo(a.q or ""); self.say(a.reply, instant=True)
        if a.mic:
            self.mic.show(); self.mute.show()
            if a.mic == "on": self.mic.get_style_context().add_class("on")
            if a.mic == "none": self.mic.get_style_context().add_class("off"); self.note("No microphone found", 10 ** 8)
        elif self.live:
            self.vstatus(); GLib.timeout_add_seconds(10, lambda: (self.vstatus(), True)[1])

    def _vbtn(self, kind, st):
        b = Gtk.Button(); b.get_style_context().add_class("vb"); b.set_can_focus(False)
        d = Gtk.DrawingArea(); d.set_size_request(20, 20); d.connect("draw", icon_draw(kind, st)); b.add(d); return b

    # ---------- look picker (shape + color, saved to ~/.config/grokbot/avatar.json) ----------
    def _build_picker(self):
        eb = Gtk.EventBox(name="picker", visible_window=True)
        eb.connect("button-press-event", lambda w, e: (self.close_picker(), True)[1] if e.window == w.get_window() else False)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label="Choose my look"); t.get_style_context().add_class("ttl"); col.add(t)
        sub = Gtk.Label(label="Tap a shape and a color"); sub.get_style_context().add_class("sub"); col.add(sub)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, halign=Gtk.Align.CENTER, margin_top=8)
        self.pick_shapes, self.pick_colors = {}, {}
        for i, (sid, label) in enumerate(AS.SHAPES):
            b = self._pick_btn(104, lambda w, cr, sid=sid: draw_shape_thumb(cr, w.get_allocated_width(), w.get_allocated_height(),
                               sid, self.style["color"], sid == self.style["shape"]) or False)
            b.set_tooltip_text(label); b.connect("clicked", lambda _b, sid=sid: self.set_look(shape=sid))
            grid.attach(b, i % 5, i // 5, 1, 1); self.pick_shapes[sid] = b
        col.add(grid)
        row = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER, margin_top=10)
        for cid, _hex in AS.COLORS:
            b = self._pick_btn(60, lambda w, cr, cid=cid: draw_swatch(cr, w.get_allocated_width(), w.get_allocated_height(),
                               cid, cid == self.style["color"]) or False)
            b.set_tooltip_text(cid.title()); b.connect("clicked", lambda _b, cid=cid: self.set_look(color=cid))
            row.add(b); self.pick_colors[cid] = b
        col.add(row)
        done = Gtk.Button(label="Done", name="done", halign=Gtk.Align.CENTER, margin_top=14); done.set_can_focus(False)
        done.connect("clicked", lambda *_: self.close_picker()); col.add(done)
        eb.add(col); return eb
    # ---------- journal viewer (build 14): tap the JOURNAL panel, or Super+J; Esc, Close or a tap outside closes ----------
    JOURNAL_PAGE = 40
    def _build_journal(self):
        eb = Gtk.EventBox(name="jview", visible_window=True)
        eb.connect("button-press-event", lambda w, e: (self.close_journal(), True)[1] if e.window == w.get_window() else False)
        card = self.jcard = Gtk.Box(name="jcard", orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                    halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        top = Gtk.Box(spacing=10)
        t = Gtk.Label(label="JOURNAL \u00b7 newest first", xalign=0); t.get_style_context().add_class("jttl"); top.pack_start(t, True, True, 0)
        x = Gtk.Button(label="Close  Esc", name="jclose"); x.set_can_focus(False)
        x.connect("clicked", lambda *_: self.close_journal()); top.pack_end(x, False, False, 0); card.add(top)
        sw = self.jsw = Gtk.ScrolledWindow(vexpand=True); sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.connect("edge-reached", lambda _s, pos: self._journal_more() if pos == Gtk.PositionType.BOTTOM else None)
        self.jlist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14); sw.add(self.jlist); card.add(sw)
        self.jstat = Gtk.Label(xalign=0); self.jstat.get_style_context().add_class("jdim"); card.add(self.jstat)
        eb.add(card); self.jn, self.jbusy, self.jend = 0, False, False
        return eb
    def _jlabel(self, text, cls):
        l = Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=False)
        l.get_style_context().add_class(cls); return l
    def _journal_row(self, v):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b.add(self._jlabel("%s  %s%s" % (v["time"], v["kind"].upper().replace("_", " "), "  @alpha" if v["host"] == "alpha" else ""), "jhead"))
        if v["what"]: b.add(self._jlabel(v["what"], "jwhat"))
        if v["reason"]: b.add(self._jlabel("why: " + v["reason"], "jwhy"))
        if v["result"]: b.add(self._jlabel("result: " + v["result"], "jres"))
        if v["extra"]: b.add(self._jlabel(v["extra"], "jdim"))
        b.show_all(); return b
    def _place_journal(self):
        W, H = self.win.get_allocated_width(), self.win.get_allocated_height()
        panels = self.hud is not None and not CP.hidden()
        x, bw = column(W, H, panels)                       # the same centre column as the chat bar (item 1)
        self.jcard.set_margin_start(x); self.jcard.set_margin_end(W - x - bw)   # margins, not a width: entries wrap inside
        self.jcard.set_margin_top(int(H * .08))
        # stop above the chat input so the bar stays visible and usable
        self.jcard.set_margin_bottom(int(H * .035) + max(48, self.inp.widget.get_allocated_height()) + 16)
    def open_journal(self):
        if CJ is None or self.picker.get_visible(): return
        self._place_journal()
        for c in self.jlist.get_children(): self.jlist.remove(c)
        self.jn, self.jend = 0, False; self.jstat.set_text("reading\u2026")
        self.jv.show_all(); self.jsw.get_vadjustment().set_value(0); self._journal_more()
    def close_journal(self):
        if self.jv.get_visible(): self.jv.hide(); self.inp.grab_focus_without_selecting()
    def journal_open(self): return self.jv.get_visible()
    def _journal_more(self):                               # older entries as he scrolls down
        if self.jbusy or self.jend or CJ is None: return
        self.jbusy = True; off = self.jn
        def done(rows):
            self.jbusy = False
            if isinstance(rows, Exception): self.jstat.set_text("couldn't read the journal"); return
            for v in rows: self.jlist.add(self._journal_row(v))
            self.jn += len(rows); self.jend = len(rows) < self.JOURNAL_PAGE
            self.jstat.set_text(("%d entries" % self.jn) + (" \u00b7 that's all" if self.jend else " \u00b7 scroll for older")
                                if self.jn else "nothing journaled yet")
        self.bg(lambda: CJ.entries(limit=self.JOURNAL_PAGE, offset=off), done)
    def on_hud_tap(self, w, e):
        if self.hud is None or CP.hidden() or self.picker.get_visible() or self.jv.get_visible(): return False
        if not (self.hud_key and not self.hud_key[0]): return False
        gw = w.get_window()
        if gw is None: return False
        ox, oy = gw.get_origin()[1:]
        x, y = e.x_root - ox, e.y_root - oy
        if CP.in_journal(w.get_allocated_width(), w.get_allocated_height(), x, y):
            self.open_journal(); return True
        return False
    def _pick_btn(self, size, draw):
        b = Gtk.Button(); b.get_style_context().add_class("pick"); b.set_can_focus(False)
        d = Gtk.DrawingArea(); d.set_size_request(size, size); d.connect("draw", draw); b.add(d); return b
    def open_pad(self):
        if self.a.offline: return
        import subprocess
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "cadpad.py"), "--fullscreen"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    def open_picker(self):
        self.picker.show_all(); self.look.hide(); self.pad.hide()
    def close_picker(self):
        self.picker.hide(); self.look.show(); self.pad.show(); self.inp.grab_focus_without_selecting()
    def apply_look(self, st):
        self.style = AS.clean(st); self.av.set_style(self.style)
        self.picker.queue_draw(); self.look_icon.queue_draw(); self.redraw()
    def set_look(self, shape=None, color=None):
        try: st = AS.save(shape=shape, color=color)
        except (OSError, ValueError) as e:
            print("avatar.json:", e, file=sys.stderr, flush=True)
            st = {**self.style, **({"shape": shape} if shape else {}), **({"color": color} if color else {})}
        self.apply_look(st); self.cfg_mtime = self._cfg_mtime()
    def _cfg_mtime(self):
        try: return os.stat(AS.CONFIG).st_mtime_ns
        except OSError: return None
    def _watch_cfg(self):   # novad (POST /api/avatar, the set_avatar tool) writes the file; pick it up
        m = self._cfg_mtime()
        if m != self.cfg_mtime:
            self.cfg_mtime = m; self.apply_look(AS.load())
        self._watch_hud()
        return True
    def _watch_hud(self):    # Super+C (panels-hidden) and new snapshots from cypherd
        if self.hud is None: return
        key = (CP.hidden(), CP.snapshot_mtime(), int(time.time() // 60))
        if key != self.hud_key:
            shown_changed = self.hud_key is None or key[0] != self.hud_key[0]
            self.hud_key = key
            self.hud.set_visible(not key[0]); self.hud.queue_draw()
            if shown_changed: self.on_size(self.win, self.win.get_allocation())
    def on_hud_draw(self, w, cr):      # runs every frame the window redraws: one cached blit, no file reads
        if not self.hud_key or self.hud_key[0]: return False
        W, H = w.get_allocated_width(), w.get_allocated_height()
        try:
            cr.set_source_surface(self.hud_cache.surface(W, H, key=self.hud_key), 0, 0); cr.paint()
        except Exception as e:
            print("hud:", type(e).__name__, e, file=sys.stderr, flush=True)
        return False

    # ---------- layout / rendering ----------
    def on_size(self, w, alloc):
        W, H = alloc.width, alloc.height
        panels = self.hud is not None and not CP.hidden()
        x, bw = column(W, H, panels)                                      # never under a panel
        self.av.lay["h"] = CP.avatar_h(W, H) if panels else self.base_h  # avatar fits between the columns
        if (x, bw) != getattr(self, "_col", None):                        # margins, not a minimum width: text wraps inside
            self._col = (x, bw); self.bar.set_margin_start(x); self.bar.set_margin_end(W - x - bw)
        self.bar.set_margin_bottom(int(H * .035))
        self._place_vnote(H)

    def _place_vnote(self, H=None):
        H = H or self.win.get_allocated_height()
        m = int(H * .035) + max(48, self.inp.widget.get_allocated_height()) + 14
        if m != self.vnote.get_margin_bottom(): self.vnote.set_margin_bottom(m)

    def on_tick(self, widget, clock):
        now = time.monotonic()
        if now >= self.next_due:
            dt = now - self.last; self.last = now
            self.next_due = max(self.next_due + self.av.frame_interval(), now - .01)
            self.av.tick(dt); self.redraw(); self.frames += 1
        return True

    def on_draw(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        sw, sh = max(1, int(W * self.dpr)), max(1, int(H * self.dpr))
        if not self.surf or self.surf.get_width() != sw or self.surf.get_height() != sh:
            self.surf = cairo.ImageSurface(cairo.FORMAT_RGB24, sw, sh)
        c = cairo.Context(self.surf); c.scale(self.dpr, self.dpr); self.av.draw(c, W, H)
        cr.scale(1 / self.dpr, 1 / self.dpr); cr.set_source_surface(self.surf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BILINEAR); cr.paint()
        return False

    # ---------- helpers ----------
    def set_state(self, s):
        if s != "sleeping": self.act = time.monotonic(); self.dozing = False
        self.av.set_state(s)
    DOZE_SECS = int(os.environ.get("NOVA_DOZE", "120"))
    def on_activity(self, *_):
        self.act = time.monotonic()
        if self.dozing: self.dozing = False; self.av.set_state("idle")
        return False
    def doze_check(self):
        if (not self.dozing and not self.busy and not self.pend and not self.V["rec"] and not self.V["speaking"]
                and time.monotonic() - self.act > self.DOZE_SECS):
            self.dozing = True; self.av.set_state("sleeping")
        return True
    def later(self, ms, fn):
        def run(): fn(); return False
        return GLib.timeout_add(int(ms), run)
    def clear_tms(self):
        for t in self.tms: GLib.source_remove(t) if GLib.MainContext.default().find_source_by_id(t) else None
        self.tms = []
    def set_echo(self, t, op=.45): self.echo.set_text(t); self.fe.to(op if t else 0, instant=True)
    def note(self, t, ms=3500):
        self.vnote.set_text(t); self.fv.to(1)
        if self.V["noteT"]: GLib.source_remove(self.V["noteT"]) if GLib.MainContext.default().find_source_by_id(self.V["noteT"]) else None
        self.V["noteT"] = self.later(ms, lambda: self.fv.to(0))
    def http(self, method, path, body=None, stream=None, timeout=130):
        rq = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None,
                                    {"Content-Type": "application/json"}, method=method)
        r = urllib.request.urlopen(rq, timeout=timeout)
        if stream:
            for line in r:
                if line.strip(): stream(json.loads(line))
            return None
        return json.loads(r.read())
    def bg(self, fn, done):
        def run():
            try: res = fn()
            except Exception as e: res = e
            GLib.idle_add(lambda: (done(res), False)[1])
        threading.Thread(target=run, daemon=True).start()

    # ---------- prompt flow (mirrors shell.html) ----------
    def say(self, t, err=False, instant=False):
        if self.a.ask: print("say:", "ERR" if err else "OK", t, file=sys.stderr, flush=True)
        if not err: self.speak(t)
        sc = self.reply.get_style_context(); self.reply.set_text(t)
        (sc.add_class if err else sc.remove_class)("err"); self.fr.to(1, instant=instant); self.clear_tms()
        self.set_state("idle" if err else "typing"); hold = min(14000, 3500 + len(t) * 60)
        self.tms = [self.later(min(2500, 600 + len(t) * 25), lambda: self.set_state("idle")),
                    self.later(hold, lambda: (self.fr.to(0), self.fe.to(0)))]
    def on_enter(self, e):
        q = e.get_text().strip()
        if q: self.close_journal()                    # sending a chat brings the reply back into view
        if self.pend: return self.answer(True)
        if not q or self.busy: return
        self.set_echo(q); e.set_text(""); self.clear_tms()
        if self.live: return self.ask(q)
        seq = [("thinking", 0), ("looking", 1500), ("working", 4300), ("typing", 7300), ("idle", 9300)]
        self.tms = [self.later(d, lambda s=s: (self.set_state(s), s == "idle" and self.fe.to(0))) for s, d in seq]
    def ask(self, q, via="typed"):
        self.busy = True; self.set_state("thinking"); self.fr.to(0, instant=True); st = {"done": False}
        def ev(e):
            def ui():
                if e.get("state"): self.set_state("working" if e["state"] == "working" else "thinking")
                if e.get("confirm"): self.ask_confirm(e["confirm"]); st["done"] = True
                if e.get("reply"): self.say(e["reply"]); st["done"] = True
                if e.get("error"): self.say(e.get("text") or "Something went wrong.", True); st["done"] = True
            GLib.idle_add(lambda: (ui(), False)[1])
        def done(res):
            if isinstance(res, Exception): self.say(NET_ERR, True)
            elif not st["done"]: self.say("Hmm, I lost my train of thought. Try again?", True)
            self.busy = False
        self.bg(lambda: self.http("POST", "/api/ask", {"prompt": q, "via": via}, stream=ev), lambda r: GLib.idle_add(lambda: (done(r), False)[1]))
    def ask_confirm(self, c):
        self.close_journal()                          # a confirm dialog is never hidden behind the viewer
        self.pend = c["id"]; sc = self.reply.get_style_context(); self.reply.set_text(c["text"]); sc.remove_class("err")
        self.pend_phys = bool(c.get("physical"))      # build 14 power_off: only a click on Confirm says yes
        for yes, (lab, sm, nm, key) in self.cf_lbl.items():
            lab.set_text((c.get("yes_label") if yes else c.get("no_label")) or nm if self.pend_phys else nm)
            sm.set_text(("tap" if yes else "Esc") if self.pend_phys else key)
        self.fr.to(1, instant=True); self.clear_tms(); self.set_state("idle"); sc.add_class("q"); self.cf.show()
        if self.pendT: GLib.source_remove(self.pendT)
        def expire():
            self.pendT = 0
            if self.pend:
                pid, phys = self.pend, self.pend_phys; self.end_confirm(); self.say("No answer, so I left it.", True)
                if phys and self.live:      # tell novad too, so the request cannot be confirmed late
                    self.bg(lambda: self.http("POST", "/api/confirm", {"id": pid, "yes": False}), lambda j: None)
        self.pendT = self.later((c.get("ttl") or 60) * 1000, expire)
    def end_confirm(self):
        self.pend = None; self.pend_phys = False; self.reply.get_style_context().remove_class("q"); self.cf.hide()
        if self.pendT: GLib.source_remove(self.pendT); self.pendT = 0
    def answer(self, yes, click=False):
        if not self.pend: return
        if self.pend_phys and yes and not click:          # Enter, voice or a stray key never confirms power_off
            self.note("Tap Confirm on the screen to shut down."); return
        phys = self.pend_phys
        pid = self.pend; self.end_confirm(); self.set_state("working" if yes else "idle")
        def done(j):
            if isinstance(j, Exception): self.say(NET_ERR, True)
            elif j.get("reply"): self.say(j["reply"])
            else: self.say(j.get("text") or "Something went wrong.", True)
            self.fe.to(0)
        if not self.live: return done({"reply": "Okay." if yes else "Okay, I won't."})
        if phys:
            return self.bg(lambda: confirm_click(pid, yes), done)
        self.bg(lambda: self.http("POST", "/api/confirm", {"id": pid, "yes": yes}), done)

    # ---------- keys ----------
    def on_key(self, w, e):
        k = Gdk.keyval_name(e.keyval)
        if self.picker.get_visible():
            if k in ("Escape", "Return", "KP_Enter"): self.close_picker()
            return True
        if k in ("j", "J") and e.state & Gdk.ModifierType.SUPER_MASK:          # build 14: Super+J toggles the journal
            (self.close_journal if self.jv.get_visible() else self.open_journal)(); return True
        if self.jv.get_visible():
            if k == "Escape": self.close_journal(); return True
            if k in ("Page_Up", "Page_Down", "Up", "Down", "Home", "End"):
                adj = self.jsw.get_vadjustment(); step = adj.get_page_size() * .9 if k.startswith("Page") else 40
                v = {"Page_Up": -step, "Up": -step, "Page_Down": step, "Down": step}.get(k)
                adj.set_value(0 if k == "Home" else adj.get_upper() if k == "End" else adj.get_value() + v); return True
        if self.pend and k in ("Return", "KP_Enter"): self.answer(True); return True   # power_off: refused in answer()
        if self.pend and k == "Escape": self.answer(False); return True
        if k == "Escape" and self.V["rec"]: self.V["tap"] = False; self.stop_listen(True); return True
        if k == "space" and not self.inp.get_text():
            if not self.V["rec"]: self.start_listen()
            return True
        if not self.inp.has_focus(): self.inp.grab_focus_without_selecting()
        return False
    def on_key_up(self, w, e):
        if Gdk.keyval_name(e.keyval) == "space" and self.V["rec"] and not self.V["tap"]: self.stop_listen(); return True
        return False

    # ---------- voice (push-to-talk; novad records with pw-record) ----------
    def vstatus(self):
        def done(s):
            if isinstance(s, Exception): return
            V = self.V; had = V["mic"]; V.update(mic=s.get("mic"), speaker=s.get("speaker"), muted=s.get("muted"), cap=s.get("cap_s") or 30)
            self.mic.show(); (self.mic.get_style_context().add_class if not V["mic"] else self.mic.get_style_context().remove_class)("off")
            self.mic.set_tooltip_text("Hold to talk (or hold Space)" if V["mic"] else "No microphone found")
            self.mute.set_visible(bool(V["speaker"])); self.mute.queue_draw()
            if not V["mic"] and (self.first_status or had): self.note("No microphone found", 4000)
            elif V["mic"] and not had and not self.first_status: self.note("Microphone connected", 2500)
            self.first_status = False
        self.bg(lambda: self.http("GET", "/api/voice/status", timeout=5), done)
    def start_listen(self):
        V = self.V
        if V["rec"] or self.busy: return
        if not V["mic"]: return self.note("No microphone found")
        V["rec"] = True; self.mic.get_style_context().add_class("on"); self.clear_tms(); self.fr.to(0, instant=True); self.set_state("listening")
        def done(r):
            if isinstance(r, Exception): r = {"error": "net"}
            if r.get("error"):
                V["rec"] = False; self.mic.get_style_context().remove_class("on"); self.set_state("idle")
                if r["error"] == "nomic": V["mic"] = False; self.mic.get_style_context().add_class("off")
                return self.note(r.get("text") or "Voice is unavailable.")
            V["capT"] = self.later((r.get("cap_s") or V["cap"]) * 1000, lambda: self.stop_listen(False, True))
        self.bg(lambda: self.http("POST", "/api/voice/start", {}), done)
    def stop_listen(self, cancel=False, capped=False):
        V = self.V
        if not V["rec"]: return
        V["rec"] = False
        if V["capT"] and GLib.MainContext.default().find_source_by_id(V["capT"]): GLib.source_remove(V["capT"])
        V["capT"] = 0; self.mic.get_style_context().remove_class("on"); self.set_state("idle" if cancel else "thinking")
        def done(r):
            if isinstance(r, Exception): r = {"error": "net", "text": NET_ERR}
            if cancel: return
            if r.get("error"): self.set_state("idle"); return self.note(r.get("text") or "I didn't catch that.")
            if capped or r.get("capped"): self.note("Stopped at %d seconds" % round(V["cap"]), 2500)
            if self.pend and r.get("intent"): self.set_echo(r["transcript"]); return self.answer(r["intent"] == "yes")
            if self.pend: self.set_state("idle"); return self.note("Say yes or no, or tap a button.")
            self.inp.set_text(r["transcript"]); self.set_echo(r["transcript"])
            self.later(450, lambda: (self.inp.set_text(""), self.ask(r["transcript"], "voice")))
        self.bg(lambda: self.http("POST", "/api/voice/stop", {"cancel": bool(cancel)}), done)
    def mic_down(self, *_):
        V = self.V
        if V["rec"] and V["tap"]: V["tap"] = False; self.stop_listen(); return True
        V["downAt"] = time.monotonic(); self.start_listen(); return True
    def mic_up(self, *_):
        V = self.V
        if not V["rec"]: return True
        if time.monotonic() - V["downAt"] < .35: V["tap"] = True
        else: self.stop_listen()
        return True
    def mic_touch(self, w, e):
        if e.type == Gdk.EventType.TOUCH_BEGIN: return self.mic_down()
        if e.type == Gdk.EventType.TOUCH_END: return self.mic_up()
        if e.type == Gdk.EventType.TOUCH_CANCEL and self.V["rec"] and not self.V["tap"]: self.stop_listen()
        return True
    def toggle_mute(self):
        def done(r):
            if isinstance(r, Exception): return
            self.V["muted"] = r.get("muted"); self.mute.queue_draw()
            self.note("Spoken replies off" if self.V["muted"] else "Spoken replies on", 2000)
        self.bg(lambda: self.http("POST", "/api/voice/mute", {"muted": not self.V["muted"]}), done)
    def speak(self, t):
        V = self.V
        if not self.live or not V["speaker"] or V["muted"]: return
        V["speaking"] = True
        self.later(min(2500, 600 + len(t) * 25) + 50, lambda: V["speaking"] and self.set_state("speaking"))
        def done(_):
            V["speaking"] = False
            if not V["rec"] and not self.busy and not self.pend: self.set_state("idle")
        self.bg(lambda: self.http("POST", "/api/voice/speak", {"text": t}), done)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=os.environ.get("NOVA_URL", "http://127.0.0.1:%s" % os.environ.get("NOVA_PORT", "8765")))
    p.add_argument("--offline", action="store_true", help="demo mode, no novad")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--size", type=lambda s: tuple(map(int, s.split("x"))), default=(1280, 720))
    p.add_argument("--dpr", type=float, default=.5, help="avatar render scale (0.5 = half resolution)")
    p.add_argument("--renderer", choices=["gl", "cairo"], default=os.environ.get("NOVA_RENDERER", "gl"))
    p.add_argument("--state"); p.add_argument("--sim", type=float); p.add_argument("--blink", type=float)
    p.add_argument("--confirm"); p.add_argument("--reply"); p.add_argument("--q"); p.add_argument("--mic", choices=["on", "off", "none"])
    p.add_argument("--shape", choices=AS.SHAPE_IDS, help="show this shape (not saved)")
    p.add_argument("--color", choices=AS.COLOR_IDS, help="show this color (not saved)")
    p.add_argument("--picker", action="store_true", help="open the look picker at startup")
    p.add_argument("--journal", action="store_true", help="open the journal viewer at startup (tests)")
    p.add_argument("--ask", help="type this prompt at startup (self-test)")
    p.add_argument("--quit-after", type=float, help="exit after N seconds and print frames drawn (tests)")
    p.add_argument("--no-panels", action="store_true", help="avatar only, without Cypher's HUD panels")
    a = p.parse_args()
    app = Nova(a)
    if a.quit_after:
        t0 = time.monotonic()
        def q():
            print("frames=%d fps=%.1f" % (app.frames, app.frames / (time.monotonic() - t0)), flush=True); Gtk.main_quit()
        GLib.timeout_add(int(a.quit_after * 1000), lambda: (q(), False)[1])
    if a.ask: GLib.timeout_add(1500, lambda: (app.inp.set_text(a.ask), app.on_enter(app.inp), False)[2])
    Gtk.main()

if __name__ == "__main__":
    main()
