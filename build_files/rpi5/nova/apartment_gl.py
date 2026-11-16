"""GLES2 renderer for Cypher's apartment (apartment.py): the room's triangles live in one static VBO (re-lit on the CPU
only when his mood or spot changes the lights), the figure's ~50 triangles are re-uploaded each frame, and one small
fragment shader draws the alley outside the window (buildings, the pink sign, rain) and the soft light halos.
Idle it runs at 8-12 fps (rain), walking 30 fps; the frame clock stops when the compositor hides the window."""
import ctypes, math
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import apartment as A

_gl = ctypes.CDLL("libGLESv2.so.2")
def _f(name, res, *args):
    fn = getattr(_gl, name); fn.restype = res; fn.argtypes = list(args); return fn
U, I, F, P = ctypes.c_uint, ctypes.c_int, ctypes.c_float, ctypes.c_void_p
glCreateShader = _f("glCreateShader", U, U)
glShaderSource = _f("glShaderSource", None, U, I, ctypes.POINTER(ctypes.c_char_p), P)
glCompileShader = _f("glCompileShader", None, U)
glGetShaderiv = _f("glGetShaderiv", None, U, U, ctypes.POINTER(I))
glGetShaderInfoLog = _f("glGetShaderInfoLog", None, U, I, P, ctypes.c_char_p)
glGetProgramInfoLog = _f("glGetProgramInfoLog", None, U, I, P, ctypes.c_char_p)
glCreateProgram = _f("glCreateProgram", U)
glAttachShader = _f("glAttachShader", None, U, U)
glBindAttribLocation = _f("glBindAttribLocation", None, U, U, ctypes.c_char_p)
glLinkProgram = _f("glLinkProgram", None, U)
glGetProgramiv = _f("glGetProgramiv", None, U, U, ctypes.POINTER(I))
glUseProgram = _f("glUseProgram", None, U)
glGetUniformLocation = _f("glGetUniformLocation", I, U, ctypes.c_char_p)
glUniform1f = _f("glUniform1f", None, I, F)
glUniform3f = _f("glUniform3f", None, I, F, F, F)
glUniformMatrix4fv = _f("glUniformMatrix4fv", None, I, I, ctypes.c_ubyte, ctypes.POINTER(F))
glGenBuffers = _f("glGenBuffers", None, I, ctypes.POINTER(U))
glBindBuffer = _f("glBindBuffer", None, U, U)
glBufferData = _f("glBufferData", None, U, ctypes.c_ssize_t, P, U)
glVertexAttribPointer = _f("glVertexAttribPointer", None, U, I, U, ctypes.c_ubyte, I, P)
glEnableVertexAttribArray = _f("glEnableVertexAttribArray", None, U)
glDrawArrays = _f("glDrawArrays", None, U, I, I)
glViewport = _f("glViewport", None, I, I, I, I)
glClearColor = _f("glClearColor", None, F, F, F, F)
glClear = _f("glClear", None, U)
glEnable = _f("glEnable", None, U)
glDisable = _f("glDisable", None, U)
glBlendFunc = _f("glBlendFunc", None, U, U)
glDepthMask = _f("glDepthMask", None, ctypes.c_ubyte)
glDepthFunc = _f("glDepthFunc", None, U)
glGetString = _f("glGetString", ctypes.c_char_p, U)
try: glGenVertexArrays = _f("glGenVertexArrays", None, I, ctypes.POINTER(U)); glBindVertexArray = _f("glBindVertexArray", None, U)
except AttributeError: glGenVertexArrays = None

GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_DYNAMIC_DRAW, GL_FLOAT, GL_TRIANGLES = 0x8892, 0x88E4, 0x88E8, 0x1406, 4
GL_DEPTH_TEST, GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_LEQUAL = 0x0B71, 0x0BE2, 0x0302, 0x0303, 1, 0x0203
GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT = 0x4000, 0x0100
STRIDE = 10 * 4

VS = b"""#version 100
attribute vec3 pos; attribute vec4 col; attribute vec2 uv; attribute float kind;
uniform mat4 mvp;
varying vec4 vc; varying vec2 vuv; varying float vk;
void main(){ vc = col; vuv = uv; vk = kind; gl_Position = mvp * vec4(pos, 1.0); }"""
FS = b"""#version 100
precision highp float;
varying vec4 vc; varying vec2 vuv; varying float vk;
uniform float t; uniform float rain; uniform vec3 neon; uniform float neonk;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main(){
  if (vk < 0.5 || (vk > 2.5)) { gl_FragColor = vc; return; }
  if (vk < 1.5) {                                   // the window: the alley outside, the sign, rain on the glass
    vec2 uv = vuv;
    vec3 c = mix(vec3(0.02, 0.02, 0.06), vec3(0.10, 0.03, 0.12), uv.y);
    float bx = floor(uv.x * 7.0); float bh = 0.35 + 0.5 * h(vec2(bx, 1.0));
    if (uv.y < bh && fract(uv.x * 7.0) < 0.97) {
      c = vec3(0.03, 0.03, 0.05);
      vec2 w = vec2(uv.x * 42.0, uv.y * 30.0);
      if (h(floor(w)) > 0.8 && fract(w.x) < 0.55 && fract(w.y) < 0.5) c += vec3(0.30, 0.22, 0.14);
    }
    float fl = 0.88 + 0.12 * step(0.96, h(vec2(floor(t * 9.0), 3.0)));
    float sx = abs(uv.x - 0.72);
    c += neon * neonk * fl * (0.55 * exp(-sx * sx * 30.0) + 1.4 * smoothstep(0.02, 0.0, sx) * step(0.35, uv.y) * step(uv.y, 0.85));
    float col = floor(uv.x * 70.0);
    float sp = 0.6 + 0.4 * h(vec2(col, 7.0));
    float ry = uv.y * 3.0 + t * 0.8 * sp;
    float on = step(1.0 - 0.35 * rain, h(vec2(col, floor(ry))));
    float streak = on * smoothstep(0.0, 0.7, fract(ry)) * (1.0 - smoothstep(0.08, 0.25, abs(fract(uv.x * 70.0) - 0.5)));
    c += vec3(0.6, 0.7, 0.9) * streak * 0.35;
    gl_FragColor = vec4(c, 1.0); return;
  }
  float d = length(vuv * 2.0 - 1.0);                  // glow sprite (additive)
  float a = exp(-d * d * 4.0) * vc.a * step(d, 1.0);
  gl_FragColor = vec4(vc.rgb * a, 1.0);
}"""

def _buf(data):
    return (F * len(data))(*data)

class AptRenderer:
    """The GLES work, independent of where the context comes from (Gtk.GLArea on the deck, or an offscreen EGL context
    for tests and renders: python3 apartment_gl.py --offscreen out.png)."""
    def __init__(self, ap):
        self.ap = ap; self.prog = 0; self.failed = None; self.room_ver = None; self.info = None

    def init_gl(self):
        def sh(kind, src):
            s = glCreateShader(kind); arr = (ctypes.c_char_p * 1)(src); glShaderSource(s, 1, arr, None); glCompileShader(s)
            ok = I(); glGetShaderiv(s, 0x8B81, ctypes.byref(ok))
            if not ok.value:
                buf = ctypes.create_string_buffer(4096); glGetShaderInfoLog(s, 4096, None, buf); raise RuntimeError(buf.value.decode())
            return s
        try:
            p = glCreateProgram(); glAttachShader(p, sh(0x8B31, VS)); glAttachShader(p, sh(0x8B30, FS))
            for i, n in enumerate((b"pos", b"col", b"uv", b"kind")): glBindAttribLocation(p, i, n)
            glLinkProgram(p)
            ok = I(); glGetProgramiv(p, 0x8B82, ctypes.byref(ok))
            if not ok.value:
                buf = ctypes.create_string_buffer(4096); glGetProgramInfoLog(p, 4096, None, buf); raise RuntimeError(buf.value.decode())
        except Exception as e:
            self.failed = str(e); return False
        self.prog = p; self.u = {n: glGetUniformLocation(p, n.encode()) for n in ("mvp", "t", "rain", "neon", "neonk")}
        if glGenVertexArrays:
            try: v = U(); glGenVertexArrays(1, ctypes.byref(v)); glBindVertexArray(v.value)
            except Exception: pass
        b = (U * 4)(); glGenBuffers(4, b); self.vbo = {"op": b[0], "dec": b[1], "glow": b[2], "fig": b[3]}; self.n = {}
        self.info = glGetString(0x1F01), glGetString(0x1F02)
        return True

    def _upload(self, key, data, usage):
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo[key]); self.n[key] = len(data) // 10
        if data: glBufferData(GL_ARRAY_BUFFER, len(data) * 4, _buf(data), usage)

    def _draw(self, key):
        if not self.n.get(key): return
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo[key])
        for i, (size, off) in enumerate(((3, 0), (4, 12), (2, 28), (1, 36))):
            glEnableVertexAttribArray(i); glVertexAttribPointer(i, size, GL_FLOAT, 0, STRIDE, ctypes.c_void_p(off))
        glDrawArrays(GL_TRIANGLES, 0, self.n[key])

    def _glow_data(self, cam):
        out = []
        for (c, size, col, a) in self.ap.glow_sprites():
            r, u = cam.r, cam.u
            corners = [A.add(A.add(c, A.mul(r, sx * size)), A.mul(u, sy * size)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
            for i in (0, 1, 2, 0, 2, 3):
                p = corners[i]; out += [p[0], p[1], p[2], col[0], col[1], col[2], a, uvs[i][0], uvs[i][1], 2.0]
        return out

    def render(self, W, H, s=1):
        if not self.prog: return
        ap = self.ap; cam = A.Camera(W, H)
        if self.room_ver != (ap.version, A.env_key(ap.env), W, H):
            op, dec, _ = ap.room_vertices(cam.eye)
            self._upload("op", op, GL_STATIC_DRAW); self._upload("dec", dec, GL_STATIC_DRAW)
            self.room_ver = (ap.version, A.env_key(ap.env), W, H)
        fig = []
        for (p0, p1, p2, p3, col, a, n) in ap.figure():
            q = (p0, p1, p2, p3)
            for i in (0, 1, 2, 0, 2, 3):
                p = q[i]; fig += [p[0], p[1], p[2], col[0], col[1], col[2], a, 0.0, 0.0, 0.0]
        self._upload("fig", fig, GL_DYNAMIC_DRAW)
        self._upload("glow", self._glow_data(cam), GL_DYNAMIC_DRAW)
        glViewport(0, 0, int(W * s), int(H * s))
        glClearColor(0.02, 0.02, 0.035, 1.0); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glUseProgram(self.prog)
        glUniformMatrix4fv(self.u["mvp"], 1, 0, (F * 16)(*cam.mvp()))
        glUniform1f(self.u["t"], ap.t % 1000.0); glUniform1f(self.u["rain"], ap.env["rain"])
        glUniform3f(self.u["neon"], *A.NEON_PINK); glUniform1f(self.u["neonk"], ap.env["neon"])
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL); glDepthMask(1); glDisable(GL_BLEND)
        self._draw("op")
        fa = ap.mv.alpha
        if fa >= 0.999: self._draw("fig")
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); glDepthMask(0)
        self._draw("dec")
        if 0.0 < fa < 0.999: self._draw("fig")
        glBlendFunc(GL_ONE, GL_ONE); self._draw("glow")
        glDepthMask(1); glDisable(GL_BLEND)

class AptGLView(Gtk.GLArea):
    def __init__(self, ap):
        super().__init__(); self.ap = ap; self.r = AptRenderer(ap); self.failed = None; self.info = None
        self.set_use_es(True); self.set_has_alpha(False); self.set_has_depth_buffer(True); self.set_auto_render(False)
        self.connect("realize", self._realize); self.connect("render", self._render)
    def _realize(self, *_):
        self.make_current()
        if self.get_error(): self.failed = str(self.get_error()); return
        if not self.r.init_gl(): self.failed = self.r.failed; return
        self.info = self.r.info
    def _render(self, area, ctx):
        self.r.render(self.get_allocated_width(), self.get_allocated_height(), self.get_scale_factor())
        return True

# ---------------- offscreen (tests, renders): EGL surfaceless + an FBO, read back to a PNG ----------------
def offscreen_png(path, ap, W=1280, H=720):
    egl = ctypes.CDLL("libEGL.so.1")
    def e(name, res, *args):
        fn = getattr(egl, name); fn.restype = res; fn.argtypes = list(args); return fn
    eglGetProcAddress = e("eglGetProcAddress", P, ctypes.c_char_p)
    getpd = ctypes.CFUNCTYPE(P, U, P, P)(eglGetProcAddress(b"eglGetPlatformDisplayEXT"))
    dpy = getpd(0x31DD, None, None)                    # EGL_PLATFORM_SURFACELESS_MESA
    if not dpy: raise RuntimeError("no surfaceless EGL display")
    if not e("eglInitialize", ctypes.c_uint, P, P, P)(dpy, None, None): raise RuntimeError("eglInitialize failed")
    e("eglBindAPI", ctypes.c_uint, U)(0x30A0)
    attrs = (I * 5)(0x3040, 0x0004, 0x3033, 0x0000, 0x3038)   # RENDERABLE_TYPE=ES2, SURFACE_TYPE=0
    cfg = P(); n = I()
    e("eglChooseConfig", ctypes.c_uint, P, P, ctypes.POINTER(P), I, ctypes.POINTER(I))(dpy, attrs, ctypes.byref(cfg), 1, ctypes.byref(n))
    if not n.value: raise RuntimeError("no EGL config")
    ctx = e("eglCreateContext", P, P, P, P, P)(dpy, cfg, None, (I * 3)(0x3098, 2, 0x3038))
    if not ctx or not e("eglMakeCurrent", ctypes.c_uint, P, P, P, P)(dpy, None, None, ctx): raise RuntimeError("eglMakeCurrent failed")
    gen = _f("glGenFramebuffers", None, I, ctypes.POINTER(U)); bind = _f("glBindFramebuffer", None, U, U)
    genr = _f("glGenRenderbuffers", None, I, ctypes.POINTER(U)); bindr = _f("glBindRenderbuffer", None, U, U)
    stor = _f("glRenderbufferStorage", None, U, U, I, I); att = _f("glFramebufferRenderbuffer", None, U, U, U, U)
    status = _f("glCheckFramebufferStatus", U, U); readp = _f("glReadPixels", None, I, I, I, I, U, U, P)
    fb = U(); gen(1, ctypes.byref(fb)); bind(0x8D40, fb.value)
    rb = (U * 2)(); genr(2, rb)
    bindr(0x8D41, rb[0]); stor(0x8D41, 0x8058, W, H); att(0x8D40, 0x8CE0, 0x8D41, rb[0])      # RGBA8 color
    bindr(0x8D41, rb[1]); stor(0x8D41, 0x81A5, W, H); att(0x8D40, 0x8D00, 0x8D41, rb[1])      # DEPTH16
    if status(0x8D40) != 0x8CD5: raise RuntimeError("framebuffer incomplete")
    r = AptRenderer(ap)
    if not r.init_gl(): raise RuntimeError("shader: %s" % r.failed)
    r.render(W, H, 1)
    buf = (ctypes.c_ubyte * (W * H * 4))(); readp(0, 0, W, H, 0x1908, 0x1401, buf)
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); stride = surf.get_stride(); data = surf.get_data()
    src = bytes(buf)
    for y in range(H):
        row = src[(H - 1 - y) * W * 4:(H - y) * W * 4]
        out = bytearray(W * 4); out[0::4] = row[2::4]; out[1::4] = row[1::4]; out[2::4] = row[0::4]
        data[y * stride:y * stride + W * 4] = bytes(out)
    surf.mark_dirty(); surf.write_to_png(path)
    return r.info

if __name__ == "__main__":
    import argparse, json, os, tempfile
    p = argparse.ArgumentParser(description="render the apartment with GLES offscreen (EGL surfaceless) to a PNG")
    p.add_argument("--offscreen", required=True); p.add_argument("--spot", choices=A.SPOT_NAMES, default="window")
    p.add_argument("--world"); p.add_argument("--size", default="1280x720"); p.add_argument("--settle", type=float, default=12.0)
    a = p.parse_args(); W, H = map(int, a.size.split("x"))
    tmp = tempfile.mkdtemp(); dp, wp = os.path.join(tmp, "d.json"), os.path.join(tmp, "w.json")
    json.dump({"spot": a.spot, "mood": {"label": "content", "valence": 0.2, "arousal": 0.1}}, open(dp, "w"))
    json.dump(json.load(open(a.world)) if a.world else {"weather": "a soft drizzle, warm neon"}, open(wp, "w"))
    ap = A.Apartment(dash_path=dp, world_path=wp); ap.mv = A.Mover("window"); ap.mv.go(a.spot); ap.simulate(a.settle)
    print("gl:", offscreen_png(a.offscreen, ap, W, H), "->", a.offscreen)
