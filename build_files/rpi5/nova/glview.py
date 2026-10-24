"""GPU renderer for the Nova avatar: one full-screen GLES fragment shader inside a Gtk.GLArea.
Python only steps the springs and passes ~40 uniforms per frame; all pixels are drawn by the GPU
(V3D on the Pi), at full resolution, so there is no CPU raster or upscale."""
import ctypes, math
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from avatar import Avatar

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
glUniform2f = _f("glUniform2f", None, I, F, F)
glUniform4f = _f("glUniform4f", None, I, F, F, F, F)
glUniform1fv = _f("glUniform1fv", None, I, I, ctypes.POINTER(F))
glUniform4fv = _f("glUniform4fv", None, I, I, ctypes.POINTER(F))
glGenBuffers = _f("glGenBuffers", None, I, ctypes.POINTER(U))
glBindBuffer = _f("glBindBuffer", None, U, U)
glBufferData = _f("glBufferData", None, U, ctypes.c_ssize_t, P, U)
glVertexAttribPointer = _f("glVertexAttribPointer", None, U, I, U, ctypes.c_ubyte, I, P)
glEnableVertexAttribArray = _f("glEnableVertexAttribArray", None, U)
glDrawArrays = _f("glDrawArrays", None, U, I, I)
glViewport = _f("glViewport", None, I, I, I, I)
glGetString = _f("glGetString", ctypes.c_char_p, U)
try: glGenVertexArrays = _f("glGenVertexArrays", None, I, ctypes.POINTER(U)); glBindVertexArray = _f("glBindVertexArray", None, U)
except AttributeError: glGenVertexArrays = None

VS = b"""#version 100
attribute vec2 pos; void main(){ gl_Position = vec4(pos, 0.0, 1.0); }"""
FS = b"""#version 100
precision highp float;
uniform vec2 res;            // logical px
uniform float pxs;           // device px per logical px
uniform vec4 body;           // cx, cy, rot, scl
uniform vec4 bsz;            // w, h, amp, ty
uniform vec4 glow;           // r0, r1, a0(.16gp), a1(.05gp)
uniform vec2 gc;             // glow center
uniform float w0c;
uniform vec4 wf[3];       // Fourier coeffs of the outline wobble (c1,s1,c2,s2,...)
uniform vec4 eye[2];         // x, y, lean, alpha(open)
uniform vec4 esz;            // ew, ehh, arcAlpha, lineW
uniform vec4 dots;           // gap, r, aL, aR
uniform vec2 dotsS;          // scale L, R
uniform vec4 zs[5];          // x, y, fs, alpha
const vec3 G0 = vec3(20.0,195.0,112.0)/255.0;
mat2 R(float a){ float c=cos(a), s=sin(a); return mat2(c,s,-s,c); }
float aa(float d){ return clamp(0.5 - d*pxs, 0.0, 1.0); }
float seg(vec2 p, vec2 a, vec2 b){ vec2 pa=p-a, ba=b-a; float h=clamp(dot(pa,ba)/dot(ba,ba),0.0,1.0); return length(pa-ba*h); }
vec3 bodyCol(float v){ // v in 0..1 top->bottom
  vec3 c1=vec3(19.0,188.0,108.0)/255.0, c2=vec3(18.0,178.0,102.0)/255.0, c3=vec3(17.0,170.0,97.0)/255.0;
  if(v<0.55) return G0; if(v<0.7) return mix(G0,c1,(v-0.55)/0.15);
  if(v<0.85) return mix(c1,c2,(v-0.7)/0.15); return mix(c2,c3,(v-0.85)/0.15); }
void main(){
  vec2 f = vec2(gl_FragCoord.x, res.y*pxs - gl_FragCoord.y)/pxs;
  // glow over black
  float gd = length(f-gc); float gt = clamp((gd-glow.x)/(glow.y-glow.x),0.0,1.0);
  float ga = gt<0.5 ? mix(glow.z,glow.w,gt*2.0) : mix(glow.w,0.0,(gt-0.5)*2.0);
  vec3 col = G0*ga;
  // body local coords
  vec2 p = R(-body.z)*(f-body.xy)/body.w;
  float w=bsz.x, h=bsz.y;
  float r = min(w,h)*0.5; vec2 q = vec2(max(abs(p.x)-(w*0.5-r),0.0), max(abs(p.y)-(h*0.5-r),0.0));
  float an = atan(p.y,p.x);
  float wv = w0c + wf[0].x*cos(an)+wf[0].y*sin(an)+wf[0].z*cos(2.0*an)+wf[0].w*sin(2.0*an)
           + wf[1].x*cos(3.0*an)+wf[1].y*sin(3.0*an)+wf[1].z*cos(4.0*an)+wf[1].w*sin(4.0*an)
           + wf[2].x*cos(5.0*an)+wf[2].y*sin(5.0*an)+wf[2].z*cos(6.0*an)+wf[2].w*sin(6.0*an);
  float d = length(q)-r - bsz.z*wv;
  float inB = aa(d*body.w);
  if(inB>0.0){
    vec3 bc = bodyCol(clamp(p.y/h+0.5,0.0,1.0));
    float ea = 0.0;
    for(int k=0;k<2;k++){
      vec2 e = R(-eye[k].z)*(p-eye[k].xy);
      float ew=esz.x, eh=esz.y, er=min(ew,eh)*0.5;
      vec2 eq = vec2(max(abs(e.x)-(ew*0.5-er),0.0), max(abs(e.y)-(eh*0.5-er),0.0));
      ea = max(ea, eye[k].w*aa((length(eq)-er)*body.w));
      if(esz.z>0.0){ float x=clamp(e.x,-ew*0.5,ew*0.5); float y=0.19*ew*(1.0-pow(2.0*x/ew,2.0));
        float sd = length(vec2(e.x-x, e.y-y)) ; float sl=1.0+pow(0.76*x*2.0/ew,2.0);
        ea = max(ea, esz.z*aa((sd/sqrt(sl)-esz.w*0.5)*body.w)); }
    }
    bc = mix(bc, vec3(0.0), ea);
    col = mix(col, bc, inB);
  }
  if(dots.y>0.0){
    float dl = length(p-vec2(-dots.x,0.0))-dots.y*dotsS.x, dr = length(p-vec2(dots.x,0.0))-dots.y*dotsS.y;
    col = mix(col, G0, dots.z*aa(dl*body.w)); col = mix(col, G0, dots.w*aa(dr*body.w));
  }
  vec3 zc = vec3(110.0,231.0,183.0)/255.0;
  for(int k=0;k<5;k++){ if(zs[k].w<=0.0) continue;
    vec2 z = R(0.15)*(f-zs[k].xy)/zs[k].z;   // glyph space, baseline at y=0, rotated -0.15
    float xh=0.52, zw=0.46, lw=0.075;
    float sd = min(min(seg(z,vec2(0.04,-xh),vec2(zw,-xh)), seg(z,vec2(zw,-xh),vec2(0.02,0.0))), seg(z,vec2(0.02,0.0),vec2(zw+0.02,0.0)));
    col = mix(col, zc, zs[k].w*aa((sd-lw)*zs[k].z)); }
  gl_FragColor = vec4(col,1.0);
}"""

class GLAvatar(Avatar):
    def params(self, W, H):
        """Same per-frame logic as Avatar.draw, but returns numbers instead of drawing."""
        G, t, st, R = self.G, self.t, self.state, self.R
        sl = max(0, min(1, G("sleep")))
        if sl > .35: self.wasAsleep = True
        if self.wasAsleep and sl < .25 and st != "sleeping": self.wasAsleep = False; self.blinkT = 0
        if self.blinkT < 0 and t > self.nextBlink and st != "typing" and sl < .05:
            self.blinkT = 0; self.nextBlink = t + 2 + R() * 4 + (-1.7 if R() < .2 else 0)
        lid = 1
        if self.blinkT >= 0:
            self.blinkT += getattr(self, "_last_dt", 0); p = self.blinkT / .16
            lid = 1 - math.sin(p * math.pi) * .88 if p < 1 else 1
            if p >= 1: self.blinkT = -1
        if self.forceBlink is not None: lid = self.forceBlink
        Sc = H / 720; ty = max(0, min(1, G("type"))); sb = math.sin(t * 6.283 / 4.6)
        breath = 1 + .012 * math.sin(t * 1.3) * (1 - sl) + .025 * sb * sl; exhale = max(0, -sb) * sl
        L = self.lay; h0 = H * L["h"] * breath; w0 = h0 * 1.9; cx = W * L["cx"]; cy = H * L["cy"] + sl * H * L["h"] * .05
        gl = G("glow"); gp = (.5 + .12 * math.sin(t * 1.2) + gl * (.35 + .25 * math.sin(t * 4))) * (1 - .6 * sl) * (1 + .25 * sb * sl)
        tSince = self.sT if st == "typing" else 0
        shrink = min(1, max(0, (tSince - .15) / .45)) if st == "typing" else 0; se = shrink * shrink * (3 - 2 * shrink)
        circR = h0 / 2 * (1 - .06 * ty) * (1 - se * .62)
        w = (w0 + (circR * 2 - w0) * ty) * (1 + .015 * exhale); h = (h0 + (circR * 2 - h0) * ty) * G("sy") * (1 - .03 * exhale)
        amp = h0 * .008 * (1 - ty); n1 = self.n1
        wob = [(n1(math.cos(a) * 1.5 + t * .6 + 10) + n1(math.sin(a) * 1.5 + t * .5 + 40) + .6 * n1(math.cos(a * 3) * 2 + math.sin(a * 2) + t * .9 + 70))
               for a in (i / 64 * 6.283 for i in range(64))] if amp else [0.0] * 64
        eA = max(0, 1 - ty * 2.2); lidS = lid * (1 - sl); rd = max(0, min(1, G("round")))
        eS = 1 / max(.6, G("scl")) * (.75 if st == "looking" else 1)
        ew = h0 * (.25 + .01 * rd) * eS; eh = h0 * (.46 - .2 * rd) * eS * max(lidS, .1); ehh = max(eh, 2 * Sc)
        ex = h0 * (.25 + .02 * rd) * eS; ey = -h0 * .02
        openA = eA * (1 - max(0, sl - .35) / .2) if sl < .55 else 0
        arcA = eA * min(1, (sl - .35) / .2) if sl > .35 else 0
        eyes = [(s * ex + G("lx") * h0 * .272, ey + G("ly") * h0 * .3, G("lean"), openA) for s in (-1, 1)]
        dots = (0, 0, 0, 0); dS = (1, 1)
        if ty > .02:
            rs = h0 * .1 * min(1, ty * 1.3); gap = max(circR + rs + h0 * .08, h0 * .42) * min(1, ty)
            wave = max(0, tSince - .6) if st == "typing" else 0
            pu = [(.5 + .5 * math.sin(wave * 7 - ph) if wave > 0 else 0) for ph in (0, 2)]
            dots = (gap, rs, (.42 + .4 * pu[0]) * ty, (.42 + .4 * pu[1]) * ty); dS = (1 + .12 * pu[0], 1 + .12 * pu[1])
        if sl > .6 and st == "sleeping":
            ph = math.floor(t / 1.55)
            if self.lastZ < 0: self.zs += [t - 1.4, t - 2.9]
            if ph != self.lastZ: self.lastZ = ph; self.zs.append(t)
        self.zs = [b for b in self.zs if t - b < 4.2]
        if st != "sleeping": self.lastZ = -1
        zs = []
        for b in self.zs[-5:]:
            a = (t - b) / 4.2
            zs.append((cx + w0 * .38 + a * h0 * .35 + math.sin(a * 6) * h0 * .04, cy - h0 * .4 - a * h0 * .6, h0 * (.11 + .1 * a),
                       math.sin(math.pi * min(1, a * 1.15)) * .85 * sl))
        zs += [(0, 0, 1, 0)] * (5 - len(zs))
        sy = G("sy")
        return dict(body=(cx, cy + (1 - sy) * h0 * .5, G("rot"), G("scl")), bsz=(w, h, amp, ty),
                    glow=(h0 * .45, w0 * .75, .16 * gp, .05 * gp), gc=(cx, cy), wob=wob, eyes=eyes,
                    esz=(ew, ehh, arcA, h0 * .05), dots=dots, dotsS=dS, zs=zs)

class GLView(Gtk.GLArea):
    def __init__(self, av):
        super().__init__(); self.av = av; self.prog = 0; self.failed = None
        self.set_use_es(True); self.set_has_alpha(False); self.set_has_depth_buffer(False); self.set_auto_render(False)
        self.connect("realize", self._realize); self.connect("render", self._render)
    def _realize(self, *_):
        self.make_current()
        if self.get_error(): self.failed = str(self.get_error()); return
        def sh(kind, src):
            s = glCreateShader(kind); arr = (ctypes.c_char_p * 1)(src); glShaderSource(s, 1, arr, None); glCompileShader(s)
            ok = I(); glGetShaderiv(s, 0x8B81, ctypes.byref(ok))
            if not ok.value:
                buf = ctypes.create_string_buffer(4096); glGetShaderInfoLog(s, 4096, None, buf); raise RuntimeError(buf.value.decode())
            return s
        try:
            p = glCreateProgram(); glAttachShader(p, sh(0x8B31, VS)); glAttachShader(p, sh(0x8B30, FS))
            glBindAttribLocation(p, 0, b"pos"); glLinkProgram(p)
            ok = I(); glGetProgramiv(p, 0x8B82, ctypes.byref(ok))
            if not ok.value:
                buf = ctypes.create_string_buffer(4096); glGetProgramInfoLog(p, 4096, None, buf); raise RuntimeError(buf.value.decode())
        except Exception as e:
            self.failed = str(e); return
        self.prog = p; self.u = {n: glGetUniformLocation(p, n.encode()) for n in
                                 ("res", "pxs", "body", "bsz", "glow", "gc", "w0c", "wf", "eye", "esz", "dots", "dotsS", "zs")}
        if glGenVertexArrays:
            try: v = U(); glGenVertexArrays(1, ctypes.byref(v)); glBindVertexArray(v.value)
            except Exception: pass
        b = U(); glGenBuffers(1, ctypes.byref(b)); self.vbo = b.value; glBindBuffer(0x8892, b.value)
        q = (F * 8)(-1, -1, 1, -1, -1, 1, 1, 1); glBufferData(0x8892, 32, q, 0x88E4)
        self.info = glGetString(0x1F01), glGetString(0x1F02)
    def _render(self, area, ctx):
        if not self.prog: return True
        W, H = self.get_allocated_width(), self.get_allocated_height(); s = self.get_scale_factor()
        k = self.av.params(W, H); u = self.u
        glViewport(0, 0, W * s, H * s); glUseProgram(self.prog)
        glUniform2f(u["res"], W, H); glUniform1f(u["pxs"], s)
        glUniform4f(u["body"], *k["body"]); glUniform4f(u["bsz"], *k["bsz"]); glUniform4f(u["glow"], *k["glow"])
        glUniform2f(u["gc"], *k["gc"]); wb = k["wob"]; c = [sum(wb[i] * math.cos(2 * math.pi * m * i / 64) for i in range(64)) / 32 for m in range(7)]
        sn = [sum(wb[i] * math.sin(2 * math.pi * m * i / 64) for i in range(64)) / 32 for m in range(7)]
        glUniform1f(u["w0c"], c[0] / 2); glUniform4fv(u["wf"], 3, (F * 12)(*[x for m in range(1, 7) for x in (c[m], sn[m])]))
        glUniform4fv(u["eye"], 2, (F * 8)(*k["eyes"][0], *k["eyes"][1])); glUniform4f(u["esz"], *k["esz"])
        glUniform4f(u["dots"], *k["dots"]); glUniform2f(u["dotsS"], *k["dotsS"])
        glUniform4fv(u["zs"], 5, (F * 20)(*[x for z in k["zs"] for x in z]))
        glBindBuffer(0x8892, self.vbo)
        glEnableVertexAttribArray(0); glVertexAttribPointer(0, 2, 0x1406, 0, 0, None); glDrawArrays(5, 0, 4)
        return True
