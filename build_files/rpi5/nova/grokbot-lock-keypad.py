#!/usr/bin/python3
"""Nova keypad lock screen for the Raspberry Pi 5 image (replaces swaylock in grokbot-lock).

A real session lock: ext-session-lock-v1 through gtk4-layer-shell's Gtk4SessionLock.
sway keeps the session locked (and blanks outputs) even if this process dies, until a
new locker unlocks it. The PIN is the user's unix password, checked through PAM
(/etc/pam.d/grokbot-lock), like swaylock. Repeated wrong PINs back off: after 5 wrong
tries each next try waits 30 s, doubling up to 15 min.

  grokbot-lock-keypad            lock now (exits after unlock)
  grokbot-lock-keypad -f         lock, return once the session is locked (like swaylock -f)
  grokbot-lock-keypad --preview  normal window, no lock, no PAM (design check)
"""
import os, pwd, sys, threading, time
from ctypes import CDLL

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
PREVIEW = "--preview" in sys.argv
READY_FD = None
if "-f" in sys.argv and not PREVIEW:
    # Fork before GTK starts. The parent exits 0 once the child reports "locked",
    # 1 if it does not within 10 s, so callers can suspend only after locking.
    r, w = os.pipe()
    if os.fork():
        os.close(w)
        import select
        ok = select.select([r], [], [], 10)[0] and os.read(r, 1) == b"L"
        os._exit(0 if ok else 1)
    os.close(r)
    os.setsid()
    READY_FD = w
if not PREVIEW:
    CDLL("libgtk4-layer-shell.so.0")  # must load before libwayland-client
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402
if not PREVIEW:
    gi.require_version("Gtk4SessionLock", "1.0")
    from gi.repository import Gtk4SessionLock as SessionLock  # noqa: E402
from lockscene import LockScene  # noqa: E402
import pamauth  # noqa: E402

USER = pwd.getpwuid(os.getuid()).pw_name
MAX_LEN = 64
FREE_TRIES, BASE_WAIT, MAX_WAIT = 5, 30, 900


class Locker:
    def __init__(self, app):
        self.app = app
        self.secret = []
        self.fails = 0
        self.wait_until = 0.0
        self.scene = LockScene()
        self.areas = []
        self.last = time.monotonic()
        if PREVIEW:
            self.lock = None
        else:
            self.lock = SessionLock.Instance.new()
            self.lock.connect("monitor", self.on_monitor)
            self.lock.connect("locked", self.on_locked)
            self.lock.connect("failed", lambda *_: (print("grokbot-lock-keypad: lock failed", file=sys.stderr), app.quit()))
            self.lock.connect("unlocked", lambda *_: app.quit())

    def start(self):
        if PREVIEW:
            w = Gtk.Window(application=self.app, title="Pixel lock (preview)")
            w.set_default_size(1280, 720)
            self.attach(w)
            w.present()
        else:
            self.lock.lock()
        GLib.timeout_add(50, self.on_tick)  # 20 fps, the sleeping rate of the app

    def on_locked(self, *_):
        global READY_FD
        if READY_FD is not None:
            os.write(READY_FD, b"L")
            os.close(READY_FD)
            READY_FD = None

    def on_monitor(self, _lock, monitor):
        w = Gtk.Window(application=self.app)
        self.attach(w)
        self.lock.assign_window_to_monitor(w, monitor)

    def attach(self, w):
        area = Gtk.DrawingArea(hexpand=True, vexpand=True, can_focus=True, focusable=True)
        area.set_draw_func(lambda a, cr, W, H: self.scene.draw(cr, W, H))
        click = Gtk.GestureClick()
        click.connect("pressed", self.on_press)
        click.connect("released", self.on_release)
        area.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        w.add_controller(keys)
        w.set_child(area)
        self.areas.append(area)
        area.grab_focus()

    def redraw(self):
        for a in self.areas:
            a.queue_draw()

    def on_tick(self):
        now = time.monotonic()
        self.scene.tick(min(.1, now - self.last))
        self.last = now
        if self.wait_until and now >= self.wait_until and not self.scene.busy:
            self.wait_until = 0.0
            self.scene.hint = "Enter PIN"
        self.redraw()
        return True

    def on_press(self, g, _n, x, y):
        self.scene.pressed = self.scene.hit(x, y)
        self.redraw()

    def on_release(self, g, _n, x, y):
        k = self.scene.hit(x, y)
        self.scene.pressed = None
        if k:
            self.key(k)

    def on_key(self, _c, keyval, _code, _state):
        name = Gdk.keyval_name(keyval) or ""
        if name in ("Return", "KP_Enter"):
            self.key("ok")
        elif name == "BackSpace":
            self.key("del")
        elif name == "Escape":
            self.clear()
        else:
            ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
            if ch and ch.isprintable():
                self.key(ch)
        return True

    def clear(self):
        self.secret.clear()
        self.scene.n = 0
        self.redraw()

    def key(self, k):
        if self.scene.busy:
            return
        if k == "del":
            if self.secret:
                self.secret.pop()
        elif k == "ok":
            return self.submit()
        elif len(self.secret) < MAX_LEN:
            self.secret.append(k)
        self.scene.n = len(self.secret)
        self.redraw()

    def submit(self):
        if not self.secret:
            return
        left = self.wait_until - time.monotonic()
        if left > 0:
            self.scene.hint = "Too many tries. Wait %d s." % (int(left) + 1)
            self.clear()
            return
        secret = "".join(self.secret)
        self.clear()
        self.scene.busy = True
        self.scene.hint = "Checking…"
        threading.Thread(target=self.check, args=(secret,), daemon=True).start()

    def check(self, secret):
        ok = True if PREVIEW else pamauth.authenticate(USER, secret)
        del secret
        GLib.idle_add(self.result, ok)

    def result(self, ok):
        self.scene.busy = False
        if ok:
            self.fails = 0
            if self.lock:
                self.lock.unlock()
            else:
                self.app.quit()
            return False
        self.fails += 1
        self.scene.wrong()
        if self.fails >= FREE_TRIES:
            wait = min(MAX_WAIT, BASE_WAIT * 2 ** (self.fails - FREE_TRIES))
            self.wait_until = time.monotonic() + wait
            self.scene.hint = "Too many tries. Wait %d s." % wait
        else:
            self.scene.hint = "Wrong PIN. Try again."
        self.redraw()
        return False


def main():
    app = Gtk.Application(application_id="os.grokbot.NovaLock" + (".Preview" if PREVIEW else ""))
    holder = {}

    def activate(a):
        holder["l"] = Locker(a)
        holder["l"].start()
        a.hold()

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
