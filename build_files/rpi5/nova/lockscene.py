"""Deck lock screen scene: Cypher asleep in his apartment (build 16: one still apartment.py frame of the bed,
drawn once per size and dimmed), the clock, PIN dots and a phone-style keypad on the right. Pure cairo, so it
renders headless for tests and screenshots; grokbot-lock-keypad puts it on a session-lock surface. (Until build
16 this was the sleeping flat avatar; that version is archived in archive/avatar-v1.)"""
import json, math, os, tempfile, time
import cairo
import apartment

KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "del", "0", "ok"]
MAX_DOTS = 12
FONT = "Nunito"


class LockScene:
    def __init__(self, rng=None):
        self.ap = self._bed_scene()
        self.state = "sleeping"
        self.bg = None          # (W, H, surface): the room is still, so it is drawn once per size
        self.n = 0              # typed characters (the secret lives in the window, not here)
        self.hint = "Enter PIN"
        self.pressed = None
        self.shake_t = -1.0
        self.busy = False
        self.W = self.H = 0

    @staticmethod
    def _bed_scene():
        """His room with him asleep on the mattress, whatever he was doing (the lock is the deck asleep). Lights
        and weather still come from his live world.json; dash.json's spot is replaced by the bed."""
        try:
            with open(apartment.DASH) as fh: d = json.load(fh)
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        d["spot"] = "bed"
        with tempfile.TemporaryDirectory() as tmp:
            dp = os.path.join(tmp, "dash.json")
            with open(dp, "w") as fh: json.dump(d, fh)
            ap = apartment.Apartment(dash_path=dp, world_path=apartment.WORLD)
            ap.dash_path = dp + ".gone"          # never re-reads the temp file once it is removed
        ap.mv = apartment.Mover("bed"); ap.set_state("sleeping"); ap.simulate(0.5)
        return ap

    def _background(self, W, H):
        if self.bg is None or self.bg[:2] != (W, H):
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, W), max(1, H)); c = cairo.Context(surf)
            c.set_source_rgb(0, 0, 0); c.paint()
            c.save(); c.translate(-W * .30, 0)        # slide the room left so the mattress sits clear of the keypad
            self.ap.draw(c, W, H); c.restore()
            g = cairo.LinearGradient(W * .45, 0, W * .62, 0)          # the keypad side darker so the keys read
            g.add_color_stop_rgba(0, 0, 0, 0, .25); g.add_color_stop_rgba(1, 0, 0, 0, .72)
            c.set_source(g); c.paint()
            c.set_source_rgba(0, 0, 0, .35); c.rectangle(0, 0, W, 112 * min(W / 1280, H / 720)); c.fill()   # behind the clock
            self.bg = (W, H, surf)
        return self.bg[2]

    # geometry -------------------------------------------------------------
    def _layout(self, W, H):
        k = min(W / 1280, H / 720)
        r = 42 * k
        gx, gy = 30 * k, 14 * k
        cx0 = W * .75
        top = H * .5 - (4 * 2 * r + 3 * gy) / 2 + 60 * k
        return k, r, gx, gy, cx0, top

    def key_rects(self, W, H):
        k, r, gx, gy, cx0, top = self._layout(W, H)
        out = []
        for i, key in enumerate(KEYS):
            col, row = i % 3, i // 3
            cx = cx0 + (col - 1) * (2 * r + gx)
            cy = top + r + row * (2 * r + gy)
            out.append((key, cx, cy, r))
        return out

    def hit(self, x, y):
        for key, cx, cy, r in self.key_rects(self.W, self.H):
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r * 1.1) ** 2:
                return key
        return None

    def wrong(self):
        self.shake_t = 0.0

    def tick(self, dt):
        if self.shake_t >= 0:
            self.shake_t += dt
            if self.shake_t > .42:
                self.shake_t = -1.0

    # drawing --------------------------------------------------------------
    def _text(self, cr, s, x, y, size, alpha=1.0, weight=cairo.FONT_WEIGHT_NORMAL):
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, weight)
        cr.set_font_size(size)
        ext = cr.text_extents(s)
        cr.set_source_rgba(1, 1, 1, alpha)
        cr.move_to(x - ext.x_advance / 2, y)
        cr.show_text(s)

    def draw(self, cr, W, H, now=None):
        self.W, self.H = W, H
        cr.set_source_surface(self._background(W, H), 0, 0); cr.paint()   # the still room, cached
        k, r, gx, gy, cx0, top = self._layout(W, H)
        lt = time.localtime(now if now is not None else time.time())
        self._text(cr, time.strftime("%-I:%M", lt), W / 2, 70 * k, 44 * k)
        self._text(cr, time.strftime("%A, %B %-d", lt), W / 2, 96 * k, 16 * k, .6)
        self._text(cr, self.hint, cx0, top - 66 * k, 15 * k, .55)
        # dots
        n = min(max(self.n, 6), MAX_DOTS)
        dr, dg = 7 * k, 16 * k
        span = n * 2 * dr + (n - 1) * dg
        sx = 0.0
        if self.shake_t >= 0:
            p = self.shake_t / .42
            sx = math.sin(p * math.pi * 5) * 12 * k * (1 - p)
        x0 = cx0 - span / 2 + dr + sx
        dy = top - 34 * k
        for i in range(n):
            cr.arc(x0 + i * (2 * dr + dg), dy, dr - k, 0, 2 * math.pi)
            if i < self.n:
                cr.set_source_rgba(1, 1, 1, 1)
                cr.fill()
            else:
                cr.set_source_rgba(1, 1, 1, .55)
                cr.set_line_width(2 * k)
                cr.stroke()
        # keys
        for key, cx, cy, kr in self.key_rects(W, H):
            if key == "ok":
                cr.set_source_rgb(20 / 255, 195 / 255, 112 / 255)
            elif key == "del":
                cr.set_source_rgba(0, 0, 0, 0)
            else:
                v = .23 if self.pressed == key else .11
                cr.set_source_rgb(v, v + .01, v + .005)
            cr.arc(cx, cy, kr, 0, 2 * math.pi)
            cr.fill()
            if key == "ok":
                cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(17 * k)
                e = cr.text_extents("OK")
                cr.set_source_rgb(4 / 255, 23 / 255, 13 / 255)
                cr.move_to(cx - e.x_advance / 2, cy + e.height / 2)
                cr.show_text("OK")
            elif key == "del":
                self._text(cr, "Delete", cx, cy + 6 * k, 17 * k, .9 if self.pressed != key else .6)
            else:
                cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                cr.set_font_size(32 * k)
                e = cr.text_extents(key)
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(cx - e.x_advance / 2 - e.x_bearing, cy + e.height / 2)
                cr.show_text(key)


def render_png(path, W=1280, H=720, typed=0, hint="Enter PIN"):
    import random
    s = LockScene(rng=random.Random(7))
    s.n, s.hint = typed, hint
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    s.draw(cairo.Context(surf), W, H, now=0)
    surf.write_to_png(path)
