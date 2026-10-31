"""Nova avatar: a faithful pycairo port of the canvas drawing in nova-shell/shell.html.
No GTK here, so it can be rendered headless (tests, screenshots)."""
import math, random, cairo
import avatar_shapes as AS

ALIAS = {"speaking": "working", "describing": "working", "handling": "thinking"}
STATES = ("idle", "thinking", "looking", "working", "typing", "sleeping", "listening")
D = math.pi / 180
GREEN = (20 / 255, 195 / 255, 112 / 255)
# frame interval per state (s): active ~40 fps, idle 30, sleeping 20
FRAME = {"sleeping": 0.050, "idle": 0.033}
ACTIVE_FRAME = 0.025

def rgb(r, g, b): return (r / 255, g / 255, b / 255)

class Avatar:
    def __init__(self, layout=None, rng=None, style=None):
        self.R = (rng or random.Random()).random
        self.P = [self.R() for _ in range(512)]
        self.lay = {"cx": .5, "cy": .43, "h": .55, **(layout or {})}
        self.state, self.sT, self.nextMove = "idle", 0.0, 0.0
        self.sp = {}
        for n, v in (("scl", 1), ("rot", 0), ("lx", 0), ("ly", 0), ("lean", 0), ("round", 0),
                     ("type", 0), ("sy", 1), ("glow", 0), ("sleep", 0)):
            self.sp[n] = [float(v), 0.0, float(v)]   # x, v, target
        self.nextBlink = 1.5 + self.R() * 3; self.blinkT = -1.0
        self.forceBlink = None
        self.zs, self.lastZ, self.wasAsleep = [], -1, False
        self.t = 0.0
        # body gradient is the same every frame apart from height: cache per rounded size
        self._bg_cache = {}
        self.set_style(style or AS.DEFAULT)

    # ---------- shape and color (avatar_shapes.py) ----------
    def set_style(self, style=None, shape=None, color=None):
        st = AS.clean({**getattr(self, "style", AS.DEFAULT), **(style or {}),
                       **({"shape": shape} if shape else {}), **({"color": color} if color else {})})
        self.style = st; sh = st["shape"]
        self.col = AS.color_rgb(st["color"])
        self.zcol = tuple(c + (1 - c) * .55 for c in self.col)   # sleeping z's: a light tint
        self.ser = AS.series(sh); self.ext = AS.extent(sh)
        self.rmax = max(math.hypot(x, y) for x, y, _ in AS.outline(sh, 128))
        self.unit = [r for _, _, r in AS.outline(sh, 140)]
        self.eyes = AS.EYES.get(sh, (0, 0, 1))
        return st

    def geom(self, h0, ty, circR, exhale):
        """Shared by both renderers: body scale and eye placement for the current shape."""
        G = self.G
        cap = self.style["shape"] == "capsule"
        S = h0 / (2 * AS.CAPSULE_H) if cap else h0 * AS.SIZE
        sx = 1 + .015 * exhale; sy = G("sy") * (1 - .03 * exhale)
        ytop = (self.ext[1] * S * (1 - ty) - circR * ty) * sy; ybot = (self.ext[3] * S * (1 - ty) + circR * ty) * sy
        dx, dy, es = self.eyes
        if not cap: es *= AS.EYE_K
        return dict(S=S, sx=sx, sy=sy, ytop=ytop, ybot=ybot, ecx=dx * S * (1 - ty), ecy=dy * S * (1 - ty), es=es,
                    mv=1.0 if cap else .7, half_w=max(abs(self.ext[0]), self.ext[2]) * S)

    def frame_interval(self): return FRAME.get(self.state, ACTIVE_FRAME)

    def set_state(self, s):
        s = ALIAS.get(s, s)
        if s not in STATES: s = "idle"
        if s != self.state: self.state, self.sT, self.nextMove = s, 0.0, 0.0

    # springs: slightly underdamped
    def T(self, n, v): self.sp[n][2] = v
    def G(self, n): return self.sp[n][0]
    def step_springs(self, DT):
        n = max(1, math.ceil(DT / .008)); dt = DT / n
        for _ in range(n):
            for k, p in self.sp.items():
                K = 45 if k == "sleep" else 170 if k == "type" else 260
                C = 11 if k == "sleep" else 24 if k == "type" else 22
                p[1] += ((p[2] - p[0]) * K - p[1] * C) * dt; p[0] += p[1] * dt

    def n1(self, x):
        i = math.floor(x); f = x - i; u = f * f * (3 - 2 * f)
        return self.P[i & 511] * (1 - u) + self.P[(i + 1) & 511] * u - .5

    def choreo(self, t):
        T, R, st = self.T, self.R, self.state
        if st != "typing": T("type", 0)
        T("sleep", 1 if st == "sleeping" else 0); T("scl", .78 if st == "looking" else 1)
        if st == "idle":
            T("round", 0); T("rot", 0); T("lean", 0); T("sy", 1); T("glow", 0)
            if t > self.nextMove:
                self.nextMove = t + 1.5 + R() * 4
                if R() < .45: T("lx", 0); T("ly", 0)
                else: T("lx", (R() * 2 - 1) * .5); T("ly", (R() * 2 - 1) * .3)
        elif st == "thinking":
            T("round", 1); T("rot", 0); T("lean", 0); T("sy", 1); T("glow", 1)
            if t > self.nextMove:
                self.nextMove = t + .8 + R() * 1.5; T("lx", (R() * 2 - 1) * .25); T("ly", -.1 + (R() * 2 - 1) * .15)
        elif st == "looking":
            T("glow", .3); T("sy", 1); c = self.sT % 2.8
            if c < 1.2: T("rot", 35 * D); T("lx", -.75); T("ly", -.35); T("round", 1); T("lean", 0)
            elif c < 2.0: T("rot", -12 * D); T("lx", .6); T("ly", -.15); T("round", 1); T("lean", 0)
            else: T("rot", -20 * D); T("lx", .4); T("ly", -.1); T("round", 0); T("lean", 18 * D)
        elif st == "working":
            T("round", 0); T("glow", .2)
            if t > self.nextMove:
                self.nextMove = t + .5 + R() * .8
                m = ["center", "center", "lean", "lean", "up", "down", "tiltL", "tiltR"][int(R() * 8)]
                T("rot", 0); T("lean", 0); T("sy", 1); T("lx", 0); T("ly", 0)
                if m == "lean":
                    d = -1 if R() < .5 else 1; T("lean", d * 15 * D); T("rot", -d * 6 * D); T("lx", d * .25)
                if m == "up": T("ly", -1.15); T("sy", 1.06)
                if m == "down": T("ly", .9); T("sy", .96)
                if m in ("tiltL", "tiltR"):
                    d = -1 if m == "tiltL" else 1; T("rot", d * 8 * D); T("lx", d * .4)
        elif st == "sleeping":
            T("round", 0); T("rot", 0); T("lean", 0); T("sy", 1); T("glow", 0); T("lx", 0); T("ly", .15)
        elif st == "listening":
            T("round", 0); T("rot", 0); T("lean", 0); T("sy", 1.02); T("glow", .55 + .25 * math.sin(t * 5)); T("lx", 0); T("ly", -.18)
        elif st == "typing":
            T("type", 1); T("glow", .2); T("rot", 0); T("lean", 0); T("lx", 0); T("ly", 0); T("sy", 1)

    def simulate(self, sec):   # fast-forward (same as ?sim= in shell.html)
        for i in range(int(sec * 120)):
            self.sT += 1 / 120; self.choreo(i / 120); self.step_springs(1 / 120)
        self.t += sec; self.nextBlink += sec

    def advance(self, dt):
        dt = min(.05, max(0.0, dt)); self.t += dt; self.sT += dt
        self.choreo(self.t); self.step_springs(dt)

    def draw(self, cr, W, H):
        """Draw one frame at logical size W x H (cr may be pre-scaled for half resolution)."""
        G, t, st, R = self.G, self.t, self.state, self.R
        sl = max(0, min(1, G("sleep")))
        if sl > .35: self.wasAsleep = True
        if self.wasAsleep and sl < .25 and st != "sleeping": self.wasAsleep = False; self.blinkT = 0
        if self.blinkT < 0 and t > self.nextBlink and st != "typing" and sl < .05:
            self.blinkT = 0; self.nextBlink = t + 2 + R() * 4 + (-1.7 if R() < .2 else 0)
        lid = 1
        if self.blinkT >= 0:
            self.blinkT += self._last_dt if hasattr(self, "_last_dt") else 0
            p = self.blinkT / .16; lid = 1 - math.sin(p * math.pi) * .88 if p < 1 else 1
            if p >= 1: self.blinkT = -1
        if self.forceBlink is not None: lid = self.forceBlink
        Sc = H / 720; ty = max(0, min(1, G("type")))
        sb = math.sin(t * 6.283 / 4.6)
        breath = 1 + .012 * math.sin(t * 1.3) * (1 - sl) + .025 * sb * sl
        exhale = max(0, -sb) * sl
        L = self.lay
        h0 = H * L["h"] * breath; w0 = h0 * 1.9; cx = W * L["cx"]; cy = H * L["cy"] + sl * H * L["h"] * .05
        cr.set_source_rgb(0, 0, 0); cr.paint()
        # glow: radial gradient, filled only over its own bounding box
        gl = G("glow"); gp = (.5 + .12 * math.sin(t * 1.2) + gl * (.35 + .25 * math.sin(t * 4))) * (1 - .6 * sl) * (1 + .25 * sb * sl)
        C = self.col; Sh = self.style["shape"]
        r1 = w0 * .75 if Sh == "capsule" else max(w0 * .5, self.rmax * h0 * AS.SIZE * 1.5)
        gg = cairo.RadialGradient(cx, cy, h0 * .45, cx, cy, r1)
        gg.add_color_stop_rgba(0, *C, .16 * gp); gg.add_color_stop_rgba(.5, *C, .05 * gp); gg.add_color_stop_rgba(1, *C, 0)
        cr.set_source(gg); cr.rectangle(cx - r1, cy - r1, 2 * r1, 2 * r1); cr.fill()
        tSince = self.sT if st == "typing" else 0
        shrink = min(1, max(0, (tSince - .15) / .45)) if st == "typing" else 0; se = shrink * shrink * (3 - 2 * shrink)
        circR = h0 / 2 * (1 - .06 * ty) * (1 - se * .62)
        g = self.geom(h0, ty, circR, exhale); S = g["S"]
        cr.save(); cr.translate(cx, cy + (1 - G("sy")) * h0 * .5); cr.rotate(G("rot")); cr.scale(G("scl"), G("scl"))
        N = len(self.unit); amp = h0 * .008 * (1 - ty); n1 = self.n1
        for i in range(N):
            a = i / N * 6.283; r = S * self.unit[i] * (1 - ty) + circR * ty
            d = amp * (n1(math.cos(a) * 1.5 + t * .6 + 10) + n1(math.sin(a) * 1.5 + t * .5 + 40)
                       + .6 * n1(math.cos(a * 3) * 2 + math.sin(a * 2) + t * .9 + 70)) if amp else 0
            (cr.line_to if i else cr.move_to)((r + d) * math.cos(a) * g["sx"], (r + d) * math.sin(a) * g["sy"])
        cr.close_path()
        path = cr.copy_path()
        bg = cairo.LinearGradient(0, g["ytop"], 0, g["ybot"])
        for o, k in ((0, 1), (.55, 1), (.7, .965), (.85, .913), (1, .87)):
            bg.add_color_stop_rgb(o, *(c * k for c in C))
        cr.set_source(bg); cr.fill()
        eA = max(0, 1 - ty * 2.2)
        if eA > 0:
            cr.save(); cr.append_path(path); cr.clip()
            lidS = lid * (1 - sl); rd = max(0, min(1, G("round")))
            eS = 1 / max(.6, G("scl")) * (.75 if st == "looking" else 1)
            eS *= g["es"]
            ew = h0 * (.25 + .01 * rd) * eS; eh = h0 * (.46 - .2 * rd) * eS * max(lidS, .1); ehh = max(eh, 2 * Sc)
            ex = h0 * (.25 + .02 * rd) * eS; ey = g["ecy"]
            for s in (-1, 1):
                x = g["ecx"] + s * ex + G("lx") * h0 * .272 * g["mv"]; y = ey + G("ly") * h0 * .3 * g["mv"]
                cr.save(); cr.translate(x, y); cr.rotate(G("lean"))
                if sl < .55:
                    al = eA * (1 - max(0, sl - .35) / .2); rr = min(ew / 2, ehh / 2)
                    cr.new_path(); _round_rect(cr, -ew / 2, -ehh / 2, ew, ehh, rr)
                    cr.set_source_rgba(0, 0, 0, al); cr.fill()
                if sl > .35:   # closed sleeping eye: short downward-curved arc
                    al = eA * min(1, (sl - .35) / .2)
                    cr.new_path(); cr.move_to(-ew * .5, 0)
                    # quadratic (0, ew*.38) -> cubic control points
                    q = ew * .38 * 2 / 3
                    cr.curve_to(-ew * .5 + (ew * .5) * 2 / 3, q, ew * .5 - (ew * .5) * 2 / 3, q, ew * .5, 0)
                    cr.set_line_width(h0 * .05 * min(1, g["es"] * 1.3)); cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_source_rgba(0, 0, 0, al); cr.stroke()
                cr.restore()
            cr.restore()
        if ty > .02:   # typing side dots
            rs = h0 * .1 * min(1, ty * 1.3); gap = max(circR + rs + h0 * .08, h0 * .42) * min(1, ty)
            wave = max(0, tSince - .6) if st == "typing" else 0
            for x, ph in ((-gap, 0), (gap, 2)):
                pu = .5 + .5 * math.sin(wave * 7 - ph) if wave > 0 else 0
                cr.new_path(); cr.arc(x, 0, rs * (1 + .12 * pu), 0, 6.283)
                cr.set_source_rgba(*C, (.42 + .4 * pu) * ty); cr.fill()
        cr.restore()
        # drifting z's, one per breath
        if sl > .6 and st == "sleeping":
            ph = math.floor(t / 1.55)
            if self.lastZ < 0: self.zs += [t - 1.4, t - 2.9]
            if ph != self.lastZ: self.lastZ = ph; self.zs.append(t)
        self.zs = [b for b in self.zs if t - b < 4.2]
        if st != "sleeping": self.lastZ = -1
        for b in self.zs:
            a = (t - b) / 4.2; fs = h0 * (.11 + .1 * a)
            cr.save()
            cr.select_font_face("Nunito", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(fs)
            cr.translate(cx + (w0 * .38 if Sh == "capsule" else g["half_w"] * .8) + a * h0 * .35 + math.sin(a * 6) * h0 * .04, cy - h0 * .4 - a * h0 * .6); cr.rotate(-.15)
            cr.set_source_rgba(*self.zcol, math.sin(math.pi * min(1, a * 1.15)) * .85 * sl)
            cr.move_to(0, 0); cr.show_text("z"); cr.restore()

    def tick(self, dt):
        self._last_dt = min(.05, max(0.0, dt)); self.advance(dt)

def _round_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi); cr.close_path()
