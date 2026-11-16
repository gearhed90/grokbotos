"""Cypher's apartment (unit 9C, the deck): a small low-poly 3D room that is the deck's default screen (build 16).

The room follows Cypher's own description (chat, Nov 15 2026, 7:31 PM): "Small place. One room over a wet alley, neon
bleeding pink through the blinds. Mattress on the floor, cables snaking to a crate that holds the deck. Noodle cups
stacked by the sink. The grid hums through the wall. Quiet enough."

This module has no GTK: the scene (geometry, lights from his mood), where he stands (spots from cypherd's dash.json),
how he walks between them, the swappable body asset, and a cairo painter's renderer (headless PNGs, tests, and the
fallback when GLES is unavailable). apartment_gl.py draws the same triangles with GLES2 on the Pi's V3D.

The body is ONE asset file (JSON primitives, see BODY_PATHS). Until Zack approves Cypher's own design it is the
placeholder in apartment_body_placeholder.json: a plain block figure in his color (look.py). Swapping in his design is
dropping one file; nothing else changes. The world is display only: it never decides, approves or controls anything."""
import json, math, os, time

E = os.environ.get
HOME = os.path.expanduser("~")
STATE = E("CYPHER_STATE_DIR", os.path.join(E("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "cypher"))
CFG = E("CYPHER_CONFIG_DIR", os.path.join(E("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "cypher"))
DASH = os.path.join(STATE, "dash.json")
WORLD = os.path.join(STATE, "world.json")
HERE = os.path.dirname(os.path.abspath(__file__))
# The body asset, first found wins: an explicit override (tests), the approved design Nova installs for this user,
# the approved design shipped in the image, then the placeholder.
BODY_PATHS = [p for p in (E("CYPHER_BODY_MODEL"), os.path.join(CFG, "body-model.json"),
                          "/usr/share/grokbot/cypher/apartment/body.json",
                          os.path.join(HERE, "apartment_body_placeholder.json")) if p]

MAG = (1.0, 0x2A / 255, 0x6D / 255)
CYAN = (0x05 / 255, 0xD9 / 255, 0xE8 / 255)
ACID = (0x39 / 255, 1.0, 0x14 / 255)
AMBER = (1.0, 0.72, 0.18)
NEON_PINK = (1.0, 0.22, 0.62)

# ---------------- spots: where he is in the room ----------------
# name: (x, z, yaw, pose, approach (x, z) or None). Room: x -2.5..2.5, z -2 (back wall)..2 (open front), y up.
SPOTS = {
    "window": (-0.55, -1.40, math.pi, "stand", None),           # idle / thinking: looking out at the alley
    "desk":   (-1.02, -0.65, -math.pi / 2, "sit", None),         # research, codex, look-ups: at the crate with the deck
    "bed":    (0.55, -1.45, 0.0, "lie", (0.30, -0.70)),          # sleeping / resting: the mattress on the floor
    "sink":   (-1.55, -1.55, -math.pi / 2, "stand", None),       # eating: the noodle cups
    "door":   (2.12, 0.12, math.pi / 2, "stand", None),          # on the way out / just back
    "center": (0.10, 0.25, 0.0, "stand", None),                  # fallback
}
SPOT_NAMES = tuple(SPOTS) + ("out",)
HUB = (0.0, -0.05)
WALK_MPS = 0.9
POSE_S = 0.7
FADE_S = 0.8

DESK_ACTS = ("research_lore", "write_codex", "look_up", "browse", "web_search", "x_lookup", "propose_code", "library",
             "visit_pino", "review_lessons", "ask_nova", "request_account", "message_zack", "show_note", "glance_screen")
WINDOW_ACTS = ("journal_thought", "check_grid", "none", "set_avatar_color", "speak")

def spot_from_dash(d):
    """The same mapping cypherd writes as dash['spot'] (cypherd.apartment_spot); used when an older cypherd wrote the
    snapshot without one. Display only."""
    if not isinstance(d, dict):
        return "window"
    s = d.get("spot")
    if isinstance(s, str) and s in SPOT_NAMES:
        return s
    act = str(d.get("activity") or "")
    place = str(d.get("place") or "apartment").replace(" ", "_")
    if not d.get("active", True) or act.startswith("standing by") or place != "apartment" or act.startswith("out in"):
        return "out"
    if act.startswith(("resting", "quiet hours", "offline", "paused")):
        return "bed"
    if act.startswith(("reading", "browsing", "searching", "visiting Pino", "writing", "asking", "messaging", "talking to")):
        return "desk"
    if act.startswith("eating"):
        return "sink"
    return "window"

# ---------------- small vector math ----------------
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    l = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / l, a[1] / l, a[2] / l)
def lerp(a, b, t): return tuple(x + (y - x) * t for x, y in zip(a, b))
def hexrgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

# ---------------- camera (shared with apartment_gl so both renderers frame the room the same) ----------------
CAM_EYE, CAM_TGT, CAM_FOVY = (0.25, 1.85, 3.9), (-0.05, 0.80, -1.0), 54.0

class Camera:
    def __init__(self, W, H, eye=CAM_EYE, tgt=CAM_TGT, fovy=CAM_FOVY):
        self.W, self.H, self.eye = W, H, eye
        self.f = norm(sub(tgt, eye)); self.r = norm(cross(self.f, (0, 1, 0))); self.u = cross(self.r, self.f)
        self.fovy = fovy; self.fpx = (H / 2) / math.tan(math.radians(fovy) / 2)
    def project(self, p):
        v = sub(p, self.eye); z = dot(v, self.f)
        if z < 0.05: z = 0.05
        return (self.W / 2 + dot(v, self.r) / z * self.fpx, self.H / 2 - dot(v, self.u) / z * self.fpx, z)
    def depth(self, p): return dot(sub(p, self.eye), self.f)
    def mvp(self, near=0.1, far=40.0):
        """Column-major 4x4 projection*view for GLES (same frustum as project())."""
        r, u, f, e = self.r, self.u, self.f, self.eye
        V = [[r[0], r[1], r[2], -dot(r, e)], [u[0], u[1], u[2], -dot(u, e)], [-f[0], -f[1], -f[2], dot(f, e)], [0, 0, 0, 1]]
        t = 1 / math.tan(math.radians(self.fovy) / 2); a = self.W / max(1, self.H)
        P = [[t / a, 0, 0, 0], [0, t, 0, 0], [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]]
        M = [[sum(P[i][k] * V[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        return [M[i][j] for j in range(4) for i in range(4)]

# ---------------- geometry ----------------
# kinds: 0 lit surface, 1 window (outside view + rain; procedural), 2 glow sprite, 3 decal (blended light on the floor)
SHELL, OBJ = "shell", "obj"

class Mesh:
    def __init__(self):
        self.quads = []          # (p0, p1, p2, p3, normal, albedo, emit, kind, layer, alpha, uv or None)
    def quad(self, p0, p1, p2, p3, n, col, emit=0.0, kind=0, layer=OBJ, alpha=1.0, sub_=(1, 1), uv=None):
        nu, nv = sub_
        if nu == 1 and nv == 1:
            self.quads.append((p0, p1, p2, p3, n, col, emit, kind, layer, alpha, uv)); return
        for i in range(nu):
            for j in range(nv):
                def P(a, b): return lerp(lerp(p0, p1, a), lerp(p3, p2, a), b)
                a0, a1, b0, b1 = i / nu, (i + 1) / nu, j / nv, (j + 1) / nv
                self.quads.append((P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1), n, col, emit, kind, layer, alpha, None))
    def box(self, x0, y0, z0, x1, y1, z1, col, emit=0.0, layer=OBJ, skip=(), tile=None):
        def s(w, h): return (max(1, round(w / tile)), max(1, round(h / tile))) if tile else (1, 1)
        F = {"+y": ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0), (0, 1, 0), s(x1 - x0, z1 - z0)),
             "-y": ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0, -1, 0), s(x1 - x0, z1 - z0)),
             "+z": ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0, 0, 1), s(x1 - x0, y1 - y0)),
             "-z": ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (0, 0, -1), s(x1 - x0, y1 - y0)),
             "+x": ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (1, 0, 0), s(z1 - z0, y1 - y0)),
             "-x": ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (-1, 0, 0), s(z1 - z0, y1 - y0))}
        for k, (a, b, c, d, n, sb) in F.items():
            if k not in skip:
                self.quad(a, b, c, d, n, col, emit, 0, layer, 1.0, sb)
    def glow(self, c, size, col, alpha=1.0):
        self.quads.append((c, size, None, None, (0, 0, 1), col, 0.0, 2, "glow", alpha, None))

WALL = hexrgb("4a4458"); WALL2 = hexrgb("4f4760"); FLOOR = hexrgb("3a3440"); CRATE = hexrgb("6b4a2c"); MATT = hexrgb("4a4f63")
SHEET = hexrgb("7a7f96"); CABLE = hexrgb("101014"); STEEL = hexrgb("7d838f"); CUP = hexrgb("e9e3d6"); CUPR = hexrgb("c8324a")
WIN = (-1.45, 0.30, 0.80, 2.25)     # window on the back wall: x0, x1, y0, y1
DOOR = (-0.35, 0.60, 0.0, 2.05)      # door on the right wall: z0, z1, y0, y1

def build_room():
    m = Mesh()
    T = 0.25
    m.box(-2.5, -0.1, -2.0, 2.5, 0.0, 2.0, FLOOR, layer=SHELL, skip=("-y", "+z", "-z", "+x", "-x"), tile=T)
    # back wall with the window hole (inner face +z at z=-2)
    x0, x1, y0, y1 = WIN
    for (a, b, c, d) in ((-2.5, x0, 0.0, 2.7), (x1, 2.5, 0.0, 2.7), (x0, x1, 0.0, y0), (x0, x1, y1, 2.7)):
        m.box(a, c, -2.1, b, d, -2.0, WALL, layer=SHELL, skip=("-z", "-y", "+y", "+x", "-x"), tile=T)
    m.box(-2.6, 0.0, -2.1, -2.5, 2.7, 2.0, WALL2, layer=SHELL, skip=("-x", "-y", "+y", "+z", "-z"), tile=T)    # left wall
    z0, z1, dy0, dy1 = DOOR
    for (a, b, c, d) in ((-2.1, z0, 0.0, 2.7), (z1, 2.0, 0.0, 2.7), (z0, z1, dy1, 2.7)):                        # right wall
        m.box(2.5, c, a, 2.6, d, b, WALL2, layer=SHELL, skip=("+x", "-y", "+y", "+z", "-z"), tile=T)
    # window: glass (procedural outside + rain), frame, sill, blinds half down
    m.quad((x0, y0, -2.06), (x1, y0, -2.06), (x1, y1, -2.06), (x0, y1, -2.06), (0, 0, 1), (1, 1, 1), kind=1, layer=SHELL,
           uv=((0, 0), (1, 0), (1, 1), (0, 1)))
    fr = hexrgb("15141a")
    m.box(x0 - 0.06, y0 - 0.06, -2.06, x1 + 0.06, y0, -1.86, fr)                       # sill
    m.box(x0 - 0.06, y1, -2.06, x1 + 0.06, y1 + 0.06, -1.98, fr)
    m.box(x0 - 0.06, y0, -2.06, x0, y1, -1.98, fr); m.box(x1, y0, -2.06, x1 + 0.06, y1, -1.98, fr)
    m.box((x0 + x1) / 2 - 0.02, y0, -2.06, (x0 + x1) / 2 + 0.02, y1, -2.0, fr)        # mullion
    sl = hexrgb("8d8897")
    yb = y1 - 0.06
    while yb > y0 + (y1 - y0) * 0.45:                                                   # blind slats; neon in the gaps
        m.box(x0, yb - 0.035, -1.99, x1, yb, -1.96, sl); yb -= 0.075
    m.box(x0 + 0.1, y0 + (y1 - y0) * 0.45, -1.97, x0 + 0.105, y1, -1.965, hexrgb("ccc6d6"))   # pull cord
    # light through the blinds onto the floor: pink stripes (decals)
    for i in range(6):
        zz = -1.85 + i * 0.2
        m.quad((x0 + 0.25 + i * 0.07, 0.004, zz), (x1 - 0.1 + i * 0.07, 0.004, zz), (x1 - 0.1 + i * 0.07, 0.004, zz + 0.09),
               (x0 + 0.25 + i * 0.07, 0.004, zz + 0.09), (0, 1, 0), NEON_PINK, kind=3, layer="decal", alpha=0.16 - i * 0.02)
    # mattress on the floor, sheet and pillow (right of the window, along the back wall)
    m.box(0.40, 0.0, -1.98, 2.42, 0.20, -0.92, MATT)
    m.box(0.55, 0.20, -1.95, 1.75, 0.235, -0.95, SHEET)
    m.box(1.95, 0.20, -1.85, 2.35, 0.29, -1.05, hexrgb("b9b4c8"))
    # the crate that holds the deck, with its screen (desk terminal), on the left
    m.box(-2.15, 0.0, -0.95, -1.55, 0.50, -0.35, CRATE)
    for yy in (0.16, 0.33):
        m.box(-1.555, yy, -0.95, -1.545, yy + 0.02, -0.35, hexrgb("4a3220"))
    m.box(-2.05, 0.50, -0.82, -1.80, 0.52, -0.48, hexrgb("1a1c22"))                       # the deck itself
    m.box(-2.02, 0.52, -0.80, -1.98, 0.78, -0.50, hexrgb("0d0f13"))                       # its screen housing
    m.quad((-1.979, 0.545, -0.48 - 0.30), (-1.979, 0.545, -0.52), (-1.979, 0.755, -0.52), (-1.979, 0.755, -0.78),
           (1, 0, 0), CYAN, emit=1.5)
    # cables snaking from the crate to the wall outlet and along the floor
    pts = [(-1.85, -0.35), (-1.6, -0.1), (-1.95, 0.25), (-2.2, 0.15), (-2.45, 0.30)]
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        dx, dz = bx - ax, bz - az; L = math.hypot(dx, dz); nx, nz = -dz / L * 0.022, dx / L * 0.022
        m.quad((ax - nx, 0.012, az - nz), (bx - nx, 0.012, bz - nz), (bx + nx, 0.012, bz + nz), (ax + nx, 0.012, az + nz), (0, 1, 0), CABLE)
    m.box(-2.5, 0.25, 0.24, -2.47, 0.37, 0.36, hexrgb("d9d4cc"))                         # outlet
    # sink counter in the back-left corner, noodle cups stacked by the sink, a bare bulb
    m.box(-2.48, 0.0, -1.98, -1.85, 0.86, -1.20, hexrgb("3b3742"))
    m.box(-2.48, 0.86, -1.98, -1.82, 0.90, -1.18, STEEL)
    m.box(-2.36, 0.875, -1.85, -2.02, 0.902, -1.55, hexrgb("1b1c20"))                    # basin
    m.box(-2.44, 0.90, -1.73, -2.40, 1.12, -1.69, STEEL); m.box(-2.44, 1.10, -1.73, -2.28, 1.13, -1.69, STEEL)
    for k, (cx, cz) in enumerate(((-2.06, -1.38), (-1.94, -1.30), (-2.18, -1.30))):
        for j in range(4 - k):
            y = 0.90 + j * 0.095
            m.box(cx - 0.045, y, cz - 0.045, cx + 0.045, y + 0.09, cz + 0.045, CUP if j % 2 == 0 else CUPR)
    m.box(-2.20, 2.30, -1.62, -2.16, 2.70, -1.58, CABLE)
    m.box(-2.22, 2.22, -1.64, -2.14, 2.30, -1.56, hexrgb("ffd9a0"), emit=1.2)
    # the grid humming through the wall: a conduit on the left wall with a status light
    m.box(-2.5, 2.35, -1.95, -2.44, 2.41, 1.6, hexrgb("3c4048"))
    m.box(-2.5, 0.40, -1.15, -2.44, 2.35, -1.09, hexrgb("3c4048"))
    m.box(-2.5, 1.20, -1.00, -2.43, 1.50, -0.80, hexrgb("2a2e35"))
    m.box(-2.435, 1.42, -0.93, -2.425, 1.45, -0.87, ACID, emit=2.0)
    # the door, its frame and the light over it
    m.box(2.47, 0.0, z0, 2.5, dy1, z1, hexrgb("23252c"))
    m.box(2.46, 0.95, z0 + 0.10, 2.47, 1.05, z0 + 0.16, STEEL)
    m.box(2.44, dy1, z0 - 0.05, 2.5, dy1 + 0.06, z1 + 0.05, hexrgb("15141a"))
    return m

def room_lights(env):
    """[(pos, color, intensity, falloff)] from the scene env (mood, quiet hours, desk use, out)."""
    L = [((-0.55, 1.6, -2.6), NEON_PINK, 3.2 * env["neon"], 0.30),           # the sign across the alley, through the blinds
         ((-1.75, 0.66, -0.65), CYAN, (1.1 if env["desk_on"] else 0.35), 1.6),   # the deck's screen
         ((-2.42, 1.44, -0.90), ACID, 0.18 * env["grid"], 3.0),                  # the grid light
         ((2.3, 2.12, 0.12), MAG if env["out"] else AMBER, 0.8, 1.2)]           # over the door
    if env["bulb"] > 0:
        L.append(((-2.18, 2.18, -1.60), (1.0, 0.82, 0.6), 1.6 * env["bulb"], 0.45))
    return L

def shade(p, n, albedo, emit, env, lights):
    a = env["ambient"]
    c = [a[0], a[1], a[2]]
    for (lp, lc, li, k) in lights:
        d = sub(lp, p); dist2 = dot(d, d); dist = math.sqrt(dist2) or 1
        ndl = (d[0] * n[0] + d[1] * n[1] + d[2] * n[2]) / dist
        if ndl <= 0: continue
        att = li / (1 + k * dist2)
        c[0] += lc[0] * ndl * att; c[1] += lc[1] * ndl * att; c[2] += lc[2] * ndl * att
    return tuple(min(1.0, albedo[i] * (c[i] + emit)) for i in range(3))

def scene_env(dash=None, world=None, spot="window", quiet=None):
    """Lights and weather from his mood (display only)."""
    d = dash if isinstance(dash, dict) else {}
    md = d.get("mood") if isinstance(d.get("mood"), dict) else {}
    v = md.get("valence"); a = md.get("arousal")
    v = max(-1.0, min(1.0, float(v))) if isinstance(v, (int, float)) else 0.0
    a = max(0.0, min(1.0, float(a))) if isinstance(a, (int, float)) else 0.2
    q = bool(d.get("quiet")) if quiet is None else quiet
    w = str((world or {}).get("weather") or "") if isinstance(world, dict) else ""
    rain = 0.9 if "heavy" in w or "storm" in w else 0.65 if "rain" in w else 0.4 if "drizzle" in w else 0.15 if w else max(0.15, 0.5 - v * 0.4)
    asleep = spot == "bed"
    return {"ambient": tuple(c * (0.7 if q or asleep else 1.0) * (1 + 0.35 * v) for c in (0.16, 0.14, 0.22)),
            "neon": round(0.8 + 0.5 * a, 2), "desk_on": spot == "desk", "grid": 1.0, "out": spot == "out",
            "bulb": 0.0 if (q or asleep or spot == "out") else (0.5 + 0.3 * max(0, v)), "rain": round(rain, 2),
            "label": str(md.get("label") or "")}

def env_key(env):
    return tuple(round(x, 2) if isinstance(x, float) else x for x in (env["ambient"][0], env["neon"], env["desk_on"], env["out"],
                                                                     env["bulb"], env["rain"]))

# ---------------- the body: one swappable asset ----------------
PLACEHOLDER = {"name": "placeholder", "temporary": True, "parts": [
    {"box": [-0.15, 0.0, -0.08, -0.03, 0.82, 0.08], "group": "leg_l"}, {"box": [0.03, 0.0, -0.08, 0.15, 0.82, 0.08], "group": "leg_r"},
    {"box": [-0.20, 0.82, -0.11, 0.20, 1.42, 0.11]}, {"box": [-0.29, 0.86, -0.07, -0.21, 1.40, 0.07], "group": "arm_l"},
    {"box": [0.21, 0.86, -0.07, 0.29, 1.40, 0.07], "group": "arm_r"}, {"box": [-0.12, 1.46, -0.12, 0.12, 1.72, 0.12]}]}

def load_body(paths=None):
    """(body dict, path). The first valid asset in BODY_PATHS; a broken file falls through to the next."""
    for p in paths or BODY_PATHS:
        try:
            with open(p) as f:
                b = json.load(f)
            parts = [x for x in b.get("parts") or [] if isinstance(x, dict) and isinstance(x.get("box"), list) and len(x["box"]) == 6
                     and all(isinstance(v, (int, float)) for v in x["box"])]
            if parts:
                return dict(b, parts=parts[:64]), p
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return dict(PLACEHOLDER), None

def body_quads(body, tint):
    """Local-space quads (feet at origin, facing +z) for each part: [(group, [ (p0..p3, n) ], col, emit)]."""
    out = []
    for part in body["parts"]:
        x0, y0, z0, x1, y1, z1 = part["box"]
        col = hexrgb(part["color"]) if isinstance(part.get("color"), str) and len(part["color"]) == 7 else tint
        m = Mesh(); m.box(x0, y0, z0, x1, y1, z1, col)
        out.append((part.get("group") or "", [(q[0], q[1], q[2], q[3], q[4]) for q in m.quads], col,
                    float(part.get("emit", body.get("emit", 0.25)))))
    return out

def _rot_x(p, a, pivot_y):
    y, z = p[1] - pivot_y, p[2]
    return (p[0], pivot_y + y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a))

def pose_point(p, group, pose, swing=0.0):
    """Local pose: legs fold for sitting, legs/arms swing while walking."""
    if pose == "sit":
        if group.startswith("leg"):
            q = _rot_x(p, -math.pi / 2, 0.82)
            return (q[0], q[1], q[2] * 0.55)                     # folded, cross-legged-ish
        return p
    if swing and group in ("leg_l", "arm_r"): return _rot_x(p, swing, 0.82 if group.startswith("leg") else 1.38)
    if swing and group in ("leg_r", "arm_l"): return _rot_x(p, -swing, 0.82 if group.startswith("leg") else 1.38)
    return p

def place_point(p, x, z, yaw, pose):
    """Local (posed) point -> world. 'lie' lays him on his back along +x (head toward the pillow)."""
    if pose == "lie":
        return (x + p[1], 0.235 + 0.12 + p[2], z + p[0])
    if pose == "sit":
        p = (p[0], p[1] - 0.66, p[2])
    c, s = math.cos(yaw), math.sin(yaw)
    return (x + p[0] * c + p[2] * s, p[1], z - p[0] * s + p[2] * c)

def place_normal(n, yaw, pose):
    if pose == "lie": return (n[1], n[2], n[0])
    c, s = math.cos(yaw), math.sin(yaw)
    return (n[0] * c + n[2] * s, n[1], -n[0] * s + n[2] * c)

# ---------------- moving between spots ----------------
class Mover:
    """Where the figure is and where it is going. Pure state, no drawing: tick(dt) walks, turns, sits, lies down,
    leaves through the door (fades out) and comes back the same way."""
    def __init__(self, spot="window"):
        sx, sz, yaw, pose, appr = SPOTS.get(spot if spot != "out" else "door")
        if appr: sx, sz = appr                                    # x, z are where he stands; lying uses the bed spot
        self.x, self.z, self.yaw, self.pose = sx, sz, yaw, pose
        self.spot, self.path, self.phase = spot, [], "at"
        self.alpha = 0.0 if spot == "out" else 1.0
        self.prev_pose, self.blend = pose, 1.0
        self.walk_t = 0.0; self.attention = False

    def busy(self):
        return self.phase != "at" or self.blend < 1.0 or (self.spot == "out" and self.alpha > 0) or (self.spot != "out" and self.alpha < 1)

    def go(self, spot):
        if spot not in SPOT_NAMES: spot = "window"
        if spot == self.spot: return False
        target = "door" if spot == "out" else spot
        tx, tz, _, _, appr = SPOTS[target]
        end = appr or (tx, tz)
        if self.spot == "out":                                    # back home: appear at the door, then walk in
            self.x, self.z = SPOTS["door"][0], SPOTS["door"][1]; self.pose = self.prev_pose = "stand"; self.blend = 1.0
            self.yaw = -math.pi / 2
        pts = []
        if math.hypot(end[0] - self.x, end[1] - self.z) > 1.3:
            pts.append(HUB)
        pts.append(end)
        if appr: pts.append((tx, tz))
        self.path = pts; self.spot = spot; self.phase = "getup" if self.pose != "stand" else "walk"
        if self.phase == "getup":
            self.prev_pose, self.pose, self.blend = self.pose, "stand", 0.0
        return True

    def tick(self, dt):
        dt = max(0.0, min(dt, 0.25))
        if self.blend < 1.0:
            self.blend = min(1.0, self.blend + dt / POSE_S)
            if self.blend < 1.0: return
        if self.phase == "getup":
            self.phase = "walk"
        if self.phase == "walk":
            final = SPOTS["door" if self.spot == "out" else self.spot]
            if not self.path:
                self.phase = "arrive"
            else:
                tx, tz = self.path[0]
                last_leg = len(self.path) == 1 and final[3] == "lie"
                if last_leg:                                      # onto the mattress: lie down in place
                    self.path = []; self.phase = "arrive"
                else:
                    dx, dz = tx - self.x, tz - self.z; d = math.hypot(dx, dz); step = WALK_MPS * dt
                    if d > 1e-3:
                        want = math.atan2(dx, dz); self.yaw = _turn(self.yaw, want, dt * 7.0)
                    if d <= step:
                        self.x, self.z = tx, tz; self.path.pop(0)
                    else:
                        self.x += dx / d * step; self.z += dz / d * step; self.walk_t += dt
        if self.phase == "arrive":
            fx, fz, fyaw, fpose, _ = SPOTS["door" if self.spot == "out" else self.spot]
            if fpose != self.pose:
                self.prev_pose, self.pose, self.blend = self.pose, fpose, 0.0
            self.yaw_target = fyaw; self.phase = "at"
        if self.phase == "at":
            want = getattr(self, "yaw_target", self.yaw)
            if self.attention and self.pose == "stand" and self.spot != "out":
                want = 0.0                                        # Zack is talking to him: he turns to the room
            self.yaw = _turn(self.yaw, want, dt * 4.0)
        if self.spot == "out" and self.phase == "at":
            self.alpha = max(0.0, self.alpha - dt / FADE_S)
        elif self.spot != "out":
            self.alpha = min(1.0, self.alpha + dt / FADE_S)

    def frame_poses(self):
        """[(weight, x, z, yaw, pose, swing)]: one entry, or two while a pose blends."""
        swing = 0.45 * math.sin(self.walk_t * 7.5) if self.phase == "walk" and self.path else 0.0
        def at(pose): return (SPOTS["bed"][0], SPOTS["bed"][1]) if pose == "lie" else (self.x, self.z)
        if self.blend < 1.0:
            (ax, az), (bx, bz) = at(self.prev_pose), at(self.pose)
            return [(1 - self.blend, ax, az, self.yaw, self.prev_pose, 0.0), (self.blend, bx, bz, self.yaw, self.pose, 0.0)]
        x, z = at(self.pose)
        return [(1.0, x, z, self.yaw, self.pose, swing)]

def _turn(a, b, k):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + d * min(1.0, k)

def figure_quads(bq, mv, env, lights, t=0.0):
    """World-space shaded quads for the figure this frame: [(p0..p3, col, alpha)]."""
    out = []
    if mv.alpha <= 0.01: return out
    poses = mv.frame_poses()
    bob = 0.025 * abs(math.sin(mv.walk_t * 7.5)) if mv.phase == "walk" and mv.path else 0.012 * math.sin(t * 1.3)
    for group, qs, col, emit in bq:
        for (p0, p1, p2, p3, n) in qs:
            pts = []
            for p in (p0, p1, p2, p3):
                acc = (0.0, 0.0, 0.0)
                for (w, x, z, yaw, pose, sw) in poses:
                    q = place_point(pose_point(p, group, pose, sw), x, z, yaw, pose)
                    acc = add(acc, mul(q, w))
                pts.append((acc[0], acc[1] + (bob if mv.pose != "lie" else 0.0), acc[2]))
            w, x, z, yaw, pose, _ = max(poses, key=lambda e: e[0])
            nn = place_normal(n, yaw, pose)
            cen = mul(add(add(pts[0], pts[1]), add(pts[2], pts[3])), 0.25)
            out.append((pts[0], pts[1], pts[2], pts[3], shade(cen, nn, col, emit, env, lights), mv.alpha, nn))
    return out

# ---------------- the scene object (what nova_native drives) ----------------
class Apartment:
    """What nova_native drives: tick, frame_interval, set_state (conversation states), set_style (his color), simulate."""
    IDLE_FRAME, WALK_FRAME, NIGHT_FRAME = 1 / 12, 1 / 30, 1 / 8

    def __init__(self, style=None, dash_path=None, world_path=None, body_paths=None):
        self.dash_path, self.world_path = dash_path or DASH, world_path or WORLD
        self.t = 0.0; self.state = "idle"
        self.dash, self.world, self._mt = None, None, (None, None); self._poll = 0.0
        self.body, self.body_path = load_body(body_paths)
        self.tint = (0.08, 0.76, 0.44)
        self.set_style(style)
        self.room = build_room()
        self.reload(force=True)
        self.mv = Mover(spot_from_dash(self.dash))
        self.env = scene_env(self.dash, self.world, self.mv.spot)
        self.lights = room_lights(self.env)
        self.version = 0                   # bumps when the room needs re-lighting (GL re-uploads, cairo re-caches)

    def set_style(self, style=None, **_):
        """His color (look.py: set_avatar_color / novad's set_color) tints the placeholder body."""
        try:
            import look
            st = look.clean(style or look.load()); self.tint = look.color_rgb(st["color"]); self.style = st
        except Exception:
            self.style = style or {}
        self.bq = body_quads(self.body, self.tint)
        return self.style

    def set_state(self, s):
        self.state = s
        self.mv.attention = s in ("listening", "thinking", "typing", "working", "speaking", "describing", "handling", "looking")

    def reload(self, force=False):
        def mt(p):
            try: return os.stat(p).st_mtime_ns
            except OSError: return None
        m = (mt(self.dash_path), mt(self.world_path))
        if not force and m == self._mt: return False
        self._mt = m
        for attr, p in (("dash", self.dash_path), ("world", self.world_path)):
            try:
                with open(p) as f: v = json.load(f)
                setattr(self, attr, v if isinstance(v, dict) else None)
            except (OSError, ValueError):
                setattr(self, attr, None)
        return True

    def target_spot(self):
        return spot_from_dash(self.dash)

    def caption(self):
        if self.mv.spot == "out" and self.mv.alpha <= 0.05:
            pl = str((self.dash or {}).get("place") or "Night City")
            return "Out in Night City" + ("" if pl in ("apartment", "Night City") else " \u00b7 " + pl)
        return ""

    def tick(self, dt):
        self.t += dt; self._poll += dt
        if self._poll >= 1.0:
            self._poll = 0.0
            if self.reload(): self.mv.go(self.target_spot())
        self.mv.tick(dt)
        env = scene_env(self.dash, self.world, self.mv.spot if not self.mv.busy() else "walking")   # lights follow him once there
        if env_key(env) != env_key(self.env):
            self.env = env; self.lights = room_lights(env); self.version += 1

    def simulate(self, sec):
        n = int(sec / 0.05)
        for _ in range(n): self.tick(0.05)

    def frame_interval(self):
        if self.mv.busy(): return self.WALK_FRAME
        return self.NIGHT_FRAME if self.mv.spot in ("bed", "out") else self.IDLE_FRAME

    # ---- triangles for the GL renderer ----
    def room_vertices(self, cam_eye=CAM_EYE):
        """Flat lists of floats per pass: (opaque, decal, glow). Vertex: x y z r g b a u v kind."""
        op, dec = [], []
        for (p0, p1, p2, p3, n, col, emit, kind, layer, alpha, uv) in self.room.quads:
            if kind == 2: continue
            if dot(n, sub(cam_eye, p0)) <= 0 and kind != 3: continue        # back faces
            if kind == 1:
                c = (1.0, 1.0, 1.0); uvs = uv
                verts = [(p, c, alpha, u) for p, u in zip((p0, p1, p2, p3), uvs)]
            else:
                verts = [(p, shade(p, n, col, emit, self.env, self.lights), alpha, (0, 0)) for p in (p0, p1, p2, p3)]
            tgt = dec if kind == 3 else op
            for i in (0, 1, 2, 0, 2, 3):
                p, c, a, u = verts[i]
                tgt += [p[0], p[1], p[2], c[0], c[1], c[2], a, u[0], u[1], float(kind)]
        return op, dec, self.glow_sprites()

    def glow_sprites(self):
        """[(center, size, color, alpha)] soft light halos (drawn additively)."""
        e = self.env
        g = [((-1.70, 0.65, -0.65), 0.55 if e["desk_on"] else 0.3, CYAN, 0.35 if e["desk_on"] else 0.15),
             ((-2.40, 1.435, -0.90), 0.12, ACID, 0.5 + 0.2 * math.sin(self.t * 2.1)),
             ((2.36, 2.13, 0.12), 0.22, MAG if e["out"] else AMBER, 0.45),
             ((-0.55, 1.6, -1.95), 1.6, NEON_PINK, 0.10 * e["neon"])]
        if e["bulb"] > 0: g.append(((-2.18, 2.22, -1.60), 0.5, (1.0, 0.85, 0.6), 0.35 * e["bulb"]))
        if self.mv.alpha > 0.05 and self.mv.pose != "lie" and self.mv.blend >= 1.0:
            g.append(((self.mv.x, 0.02, self.mv.z), 0.55, self.tint, 0.18 * self.mv.alpha))
        return g

    def figure(self):
        return figure_quads(self.bq, self.mv, self.env, self.lights, self.t)

    # ---- cairo painter's renderer (headless PNG + fallback) ----
    def draw(self, cr, W, H):
        cam = Camera(W, H)
        key = (W, H, self.version, env_key(self.env))
        if getattr(self, "_bg_key", None) != key:
            import cairo
            self._bg = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
            c2 = cairo.Context(self._bg); c2.set_source_rgb(0.02, 0.02, 0.035); c2.paint()
            self._draw_static(c2, cam, layers=(SHELL,), window=False)
            self._bg_key = key
        cr.set_source_surface(self._bg, 0, 0); cr.paint()
        self._draw_window(cr, cam)
        self._draw_static(cr, cam, layers=("decal",), window=False)
        items = [(cam.depth(mul(add(add(q[0], q[1]), add(q[2], q[3])), 0.25)), "room", q) for q in self.room.quads
                 if q[8] == OBJ and dot(q[4], sub(cam.eye, q[0])) > 0]
        items += [(cam.depth(mul(add(add(f[0], f[1]), add(f[2], f[3])), 0.25)) - 0.02, "fig", f) for f in self.figure()
                  if dot(f[6], sub(cam.eye, f[0])) > 0]
        items.sort(key=lambda it: -it[0])
        for _, kind, q in items:
            if kind == "room":
                col = shade(mul(add(add(q[0], q[1]), add(q[2], q[3])), 0.25), q[4], q[5], q[6], self.env, self.lights); a = 1.0
            else:
                col, a = q[4], q[5]
            self._poly(cr, cam, q[:4], col, a)
        self._draw_glows(cr, cam)

    def _poly(self, cr, cam, pts, col, alpha=1.0):
        pp = [cam.project(p) for p in pts]
        cr.move_to(pp[0][0], pp[0][1])
        for p in pp[1:]: cr.line_to(p[0], p[1])
        cr.close_path()
        if alpha >= 0.999: cr.set_source_rgb(*col)
        else: cr.set_source_rgba(col[0], col[1], col[2], alpha)
        cr.fill_preserve(); cr.set_line_width(0.6); cr.stroke()

    def _draw_static(self, cr, cam, layers, window):
        qs = [q for q in self.room.quads if q[8] in layers and q[7] in (0, 3) and (q[7] == 3 or dot(q[4], sub(cam.eye, q[0])) > 0)]
        qs.sort(key=lambda q: -cam.depth(mul(add(add(q[0], q[1]), add(q[2], q[3])), 0.25)))
        for q in qs:
            cen = mul(add(add(q[0], q[1]), add(q[2], q[3])), 0.25)
            if q[7] == 3:
                pp = [cam.project(p) for p in q[:4]]
                cr.move_to(*pp[0][:2]); [cr.line_to(*p[:2]) for p in pp[1:]]; cr.close_path()
                cr.set_source_rgba(q[5][0], q[5][1], q[5][2], q[9] * self.env["neon"]); cr.fill()
            else:
                self._poly(cr, cam, q[:4], shade(cen, q[4], q[5], q[6], self.env, self.lights))

    def _draw_window(self, cr, cam):
        import cairo
        x0, x1, y0, y1 = WIN; z = -2.06
        def P(u, v): return cam.project((x0 + (x1 - x0) * u, y0 + (y1 - y0) * v, z))[:2]
        def rect(u0, v0, u1, v1):
            a, b, c, d = P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1)
            cr.move_to(*a); cr.line_to(*b); cr.line_to(*c); cr.line_to(*d); cr.close_path()
        cr.save(); rect(0, 0, 1, 1); cr.clip()
        top, bot = P(0, 1), P(0, 0)
        g = cairo.LinearGradient(0, top[1], 0, bot[1]); g.add_color_stop_rgb(0, 0.10, 0.03, 0.12); g.add_color_stop_rgb(1, 0.02, 0.02, 0.06)
        rect(0, 0, 1, 1); cr.set_source(g); cr.fill()
        import random
        R = random.Random(9)
        for i in range(7):
            u0, u1 = i / 7, (i + 1) / 7; h = 0.35 + 0.5 * R.random()
            rect(u0, 0, u1 - 0.004, h); cr.set_source_rgb(0.03, 0.03, 0.05); cr.fill()
            for _ in range(10):
                wu, wv = u0 + R.random() * (u1 - u0 - 0.02), R.random() * (h - 0.03)
                rect(wu, wv, wu + 0.012, wv + 0.02); cr.set_source_rgb(0.30, 0.22, 0.14); cr.fill()
        n = self.env["neon"]
        cx, cy = P(0.72, 0.6)
        rg = cairo.RadialGradient(cx, cy, 2, cx, cy, 160)
        rg.add_color_stop_rgba(0, NEON_PINK[0], NEON_PINK[1], NEON_PINK[2], 0.55 * n); rg.add_color_stop_rgba(1, NEON_PINK[0], NEON_PINK[1], NEON_PINK[2], 0)
        rect(0, 0, 1, 1); cr.set_source(rg); cr.fill()
        rect(0.71, 0.35, 0.735, 0.85); cr.set_source_rgb(min(1, NEON_PINK[0] * 1.2), 0.55, 0.85); cr.fill()
        cr.set_line_width(1.0)
        rain = self.env["rain"]
        for i in range(int(90 * rain)):
            u = R.random(); v = (R.random() - self.t * 0.8 * (0.6 + 0.4 * R.random())) % 1.0
            a, b = P(u, v), P(u, max(0, v - 0.06))
            cr.move_to(*a); cr.line_to(*b); cr.set_source_rgba(0.6, 0.7, 0.9, 0.35); cr.stroke()
        cr.restore()

    def _draw_glows(self, cr, cam):
        import cairo
        for (c, size, col, a) in self.glow_sprites():
            x, y, z = cam.project(c); r = max(2.0, size * cam.fpx / z)
            g = cairo.RadialGradient(x, y, 0, x, y, r)
            g.add_color_stop_rgba(0, col[0], col[1], col[2], a); g.add_color_stop_rgba(1, col[0], col[1], col[2], 0)
            cr.save(); cr.set_operator(cairo.OPERATOR_ADD); cr.arc(x, y, r, 0, 2 * math.pi); cr.set_source(g); cr.fill(); cr.restore()

def render_png(path, size=(1280, 720), dash=None, world=None, spot=None, panels=False, settle=12.0, body_paths=None, state=None):
    """One frame to a PNG (headless). spot forces where he is; settle walks him there first."""
    import cairo, tempfile
    W, H = size
    tmp = tempfile.mkdtemp()
    dp, wp = os.path.join(tmp, "dash.json"), os.path.join(tmp, "world.json")
    d = dict(dash or {})
    if spot: d["spot"] = spot
    with open(dp, "w") as f: json.dump(d, f)
    with open(wp, "w") as f: json.dump(world or {}, f)
    ap = Apartment(dash_path=dp, world_path=wp, body_paths=body_paths)
    ap.mv = Mover("window"); ap.mv.go(ap.target_spot())
    if state: ap.set_state(state)
    ap.simulate(settle)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); cr = cairo.Context(surf)
    ap.draw(cr, W, H)
    if panels:
        try:
            import sys
            for dd in (os.path.join(HERE, "..", "cypher"), "/usr/share/grokbot/cypher"):
                if os.path.exists(os.path.join(dd, "cypher_panels.py")) and dd not in sys.path: sys.path.insert(0, dd)
            import cypher_panels as CP
            CP.render_panels(cr, W, H, dash, time.time())
        except Exception as e:
            print("panels not drawn:", type(e).__name__, e)
    surf.write_to_png(path)
    return ap

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="render Cypher's apartment to a PNG (headless)")
    p.add_argument("out"); p.add_argument("--spot", choices=SPOT_NAMES); p.add_argument("--snapshot"); p.add_argument("--world")
    p.add_argument("--panels", action="store_true"); p.add_argument("--size", default="1280x720")
    a = p.parse_args()
    ld = lambda q: json.load(open(q)) if q else None
    W, H = map(int, a.size.split("x"))
    ap = render_png(a.out, (W, H), ld(a.snapshot), ld(a.world), a.spot, a.panels)
    print("rendered", a.out, "spot", ap.mv.spot, "body", ap.body.get("name"), "from", ap.body_path or "built-in placeholder")
