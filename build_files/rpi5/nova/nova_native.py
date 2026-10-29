#!/usr/bin/env python3
"""Nova native shell for grokbotos (GTK3 + pycairo). Replaces the Firefox kiosk page.
Client of novad (http://127.0.0.1:8765). Wayland app_id is "nova-shell" so the sway
rules and novad's focus watcher keep working. No on-screen keyboard by design."""
import argparse, json, os, sys, threading, time, urllib.request, urllib.error
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import GLib
GLib.set_prgname("nova-shell")          # -> xdg app_id "nova-shell" on Wayland, WM_CLASS on X
from gi.repository import Gtk, Gdk
import cairo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from avatar import Avatar

NET_ERR = "I can't reach my helper service right now (novad)."
CSS = b"""
window, .nova { background: #000; }
#reply { color: #d1fae5; font-size: 24px; }
#reply.err { color: #fcd34d; }
#reply.q { color: #fff; font-weight: 600; background: rgba(0,0,0,.72); border-radius: 18px; padding: 8px 18px; }
#echo { color: #fff; font-size: 18px; }
#vnote { color: rgba(255,255,255,.55); font-size: 15px; }
entry#in { font-size: 20px; color: #fff; background: rgba(20,24,22,.85); background-image: none;
  border: 1px solid rgba(110,231,183,.18); border-radius: 28px; padding: 14px 110px 14px 22px; box-shadow: none; caret-color: #fff; }
entry#in:focus { border-color: rgba(110,231,183,.45); }
entry#in placeholder { color: rgba(255,255,255,.4); }
button.cf { font-size: 22px; min-width: 150px; padding: 14px 26px; border-radius: 28px; background-image: none; box-shadow: none; text-shadow: none; }
button#yes { background: #14C370; color: #04140b; border: 0; font-weight: 700; }
button#no { background: rgba(20,24,22,.7); color: #fff; border: 1px solid rgba(255,255,255,.25); }
button.cf label.small { font-size: 13px; font-weight: 400; opacity: .6; }
button.vb { min-width: 42px; min-height: 42px; padding: 0; border-radius: 21px; border: 1px solid rgba(110,231,183,.18);
  background: rgba(20,24,22,.7); background-image: none; color: #d1fae5; box-shadow: none; }
button.vb.off { opacity: .35; }
button.vb.on { background: #14C370; color: #04140b; border-color: #14C370; }
"""

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

class Nova:
    def __init__(self, a):
        self.a, self.base, self.live = a, a.base.rstrip("/"), not a.offline
        self.av = Avatar(); self.dpr = a.dpr
        if a.blink is not None: self.av.forceBlink = a.blink
        self.busy, self.pend, self.pendT, self.tms = False, None, 0, []
        self.V = dict(mic=False, speaker=False, muted=False, cap=30, rec=False, speaking=False, downAt=0, tap=False, capT=0, noteT=0)
        self.first_status = True; self.frames = 0
        prov = Gtk.CssProvider(); prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        s = Gtk.Settings.get_default(); s.set_property("gtk-application-prefer-dark-theme", True)
        w = self.win = Gtk.Window(title="Pixel"); w.get_style_context().add_class("nova")
        w.set_default_size(*a.size); w.connect("destroy", Gtk.main_quit)
        ov = Gtk.Overlay(); w.add(ov)
        if a.renderer == "gl":
            from glview import GLView, GLAvatar
            self.av = GLAvatar(); self.da = GLView(self.av); self.redraw = self.da.queue_render
            if a.blink is not None: self.av.forceBlink = a.blink
        else:
            self.da = Gtk.DrawingArea(); self.da.connect("draw", self.on_draw); self.redraw = self.da.queue_draw
        ov.add(self.da)
        self.surf = None
        # bottom bar
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.END); self.bar = bar
        self.reply = Gtk.Label(name="reply", wrap=True, justify=Gtk.Justification.CENTER, halign=Gtk.Align.CENTER, margin_bottom=12)
        self.echo = Gtk.Label(name="echo", wrap=True, justify=Gtk.Justification.CENTER, margin_bottom=10)
        self.echo.set_size_request(-1, 22)
        self.fr, self.fe = Fader(self.reply, .8), Fader(self.echo, .4)
        self.cf = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, margin_bottom=14, no_show_all=True)
        for nm, key, yes in (("Yes", "Enter", True), ("No", "Esc", False)):
            b = Gtk.Button(name=nm.lower()); b.get_style_context().add_class("cf"); b.set_can_focus(False)
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); bx.add(Gtk.Label(label=nm))
            sm = Gtk.Label(label=key); sm.get_style_context().add_class("small"); bx.add(sm); b.add(bx); bx.show_all()
            b.connect("clicked", lambda _b, y=yes: self.answer(y)); b.show(); self.cf.add(b)
        row = Gtk.Overlay()
        self.inp = Gtk.Entry(name="in", placeholder_text="Ask Pixel…"); self.inp.connect("activate", self.on_enter)
        self.inp.set_input_hints(Gtk.InputHints.INHIBIT_OSK)   # never pop an on-screen keyboard
        row.add(self.inp)
        vb = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.CENTER, margin_end=8)
        self.mute = self._vbtn("mute", lambda: self.V["muted"]); self.mic = self._vbtn("mic", None)
        self.mute.connect("clicked", lambda *_: self.toggle_mute())
        self.mic.connect("button-press-event", self.mic_down); self.mic.connect("button-release-event", self.mic_up)
        self.mic.connect("touch-event", self.mic_touch)
        vb.add(self.mute); vb.add(self.mic); row.add_overlay(vb)
        for x in (self.reply, self.echo, self.cf, row): bar.add(x)
        ov.add_overlay(bar)
        self.vnote = Gtk.Label(name="vnote", halign=Gtk.Align.CENTER, valign=Gtk.Align.END); self.fv = Fader(self.vnote, .6)
        ov.add_overlay(self.vnote); ov.set_overlay_pass_through(self.vnote, True)
        w.connect("size-allocate", self.on_size)
        w.connect("key-press-event", self.on_key); w.connect("key-release-event", self.on_key_up)
        w.show_all(); self.mute.hide(); self.mic.hide()
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
        GLib.timeout_add_seconds(5, self.doze_check)
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

    # ---------- layout / rendering ----------
    def on_size(self, w, alloc):
        W, H = alloc.width, alloc.height
        self.bar.set_size_request(min(720, int(W * .8)), -1); self.bar.set_margin_bottom(int(H * .035))
        self.vnote.set_margin_bottom(int(H * .035) + 62)
        self.reply.set_max_width_chars(60)

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
        self.pend = c["id"]; sc = self.reply.get_style_context(); self.reply.set_text(c["text"]); sc.remove_class("err")
        self.fr.to(1, instant=True); self.clear_tms(); self.set_state("idle"); sc.add_class("q"); self.cf.show()
        if self.pendT: GLib.source_remove(self.pendT)
        def expire():
            self.pendT = 0
            if self.pend: self.end_confirm(); self.say("No answer, so I left it.", True)
        self.pendT = self.later((c.get("ttl") or 60) * 1000, expire)
    def end_confirm(self):
        self.pend = None; self.reply.get_style_context().remove_class("q"); self.cf.hide()
        if self.pendT: GLib.source_remove(self.pendT); self.pendT = 0
    def answer(self, yes):
        if not self.pend: return
        pid = self.pend; self.end_confirm(); self.set_state("working" if yes else "idle")
        def done(j):
            if isinstance(j, Exception): self.say(NET_ERR, True)
            elif j.get("reply"): self.say(j["reply"])
            else: self.say(j.get("text") or "Something went wrong.", True)
            self.fe.to(0)
        if not self.live: return done({"reply": "Okay." if yes else "Okay, I won't."})
        self.bg(lambda: self.http("POST", "/api/confirm", {"id": pid, "yes": yes}), done)

    # ---------- keys ----------
    def on_key(self, w, e):
        k = Gdk.keyval_name(e.keyval)
        if self.pend and k in ("Return", "KP_Enter"): self.answer(True); return True
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
    p.add_argument("--ask", help="type this prompt at startup (self-test)")
    p.add_argument("--quit-after", type=float, help="exit after N seconds and print frames drawn (tests)")
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
