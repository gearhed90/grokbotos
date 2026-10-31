"""Avatar shapes and colors for the Pi avatar (Pixel), shared by the renderers, novad and the picker.
Pure Python (no cairo/GTK). Every shape is star-shaped around its center, so it is stored as a
polar radius r(theta) and reduced to a short Fourier series: the cairo renderer traces it and the
GL shader evaluates it per pixel, so both draw the same outline. Units: the radius of a circle of
the same area is 1 (the capsule keeps its own proportions, height 2*CAPSULE_H)."""
import json, math, os

SPEC_N = 256          # polar samples used to fit the series
HARM = 32             # harmonics kept (the GL shader has room for exactly this many)
CAPSULE_H = 1 / 1.462  # capsule height / 2 in equal-area units (aspect 1.9:1, as the original avatar)

# id, label, eye placement (dx, dy in body units, eye scale vs the original capsule eyes)
SHAPES = [
    ("circle", "Circle"), ("blob", "Blob"), ("diamond", "Diamond"), ("sparkle", "Sparkle"),
    ("clover", "Clover"), ("bean", "Bean"), ("scallop", "Scallop"), ("drop", "Drop"),
    ("capsule", "Capsule"), ("triangle", "Triangle"), ("house", "House"), ("star", "Star"),
    ("hexagon", "Hexagon"),
]
SHAPE_IDS = [s for s, _ in SHAPES]
COLORS = [
    ("white", "#FFFFFF"), ("brown", "#A8693A"), ("red", "#FF2D3D"), ("orange", "#FF6B1A"),
    ("amber", "#FF9F1A"), ("green", "#14C370"), ("teal", "#14B8A6"), ("blue", "#1E88FF"),
    ("purple", "#8B5CF6"), ("pink", "#FF3D8B"), ("gray", "#7A7A7A"),
]
COLOR_IDS = [c for c, _ in COLORS]
# The original Pi avatar is a green horizontal capsule, so that stays the default look.
DEFAULT = {"shape": "capsule", "color": "green"}
SIZE = .46            # equal-area radius of the other shapes, as a fraction of the capsule's height
EYE_K = SIZE / .64    # their eyes shrink with them (the EYES scales were tuned at .64)
# eye offset (x, y) and eye scale per shape; the reference art puts the eyes up and right
EYES = {
    "capsule": (0.0, -0.03, 1.0),
    "circle": (.16, -.12, .62), "blob": (.18, -.10, .62), "diamond": (.14, -.10, .60),
    "sparkle": (.10, -.06, .52), "clover": (.12, -.08, .58), "bean": (.18, -.12, .58),
    "scallop": (.12, -.08, .56), "drop": (.14, .02, .60), "triangle": (.04, .04, .52),
    "house": (.10, .00, .58), "star": (.08, -.04, .48), "hexagon": (.14, -.10, .60),
}

def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
def color_rgb(cid): return hex_rgb(dict(COLORS).get(cid, dict(COLORS)[DEFAULT["color"]]))

# ---------- 2D signed distance helpers (negative inside) ----------
def _rot(x, y, a): c, s = math.cos(a), math.sin(a); return c * x + s * y, -s * x + c * y
def _seg(px, py, ax, ay, bx, by):
    pax, pay, bax, bay = px - ax, py - ay, bx - ax, by - ay
    h = max(0, min(1, (pax * bax + pay * bay) / (bax * bax + bay * bay)))
    return math.hypot(pax - bax * h, pay - bay * h)
def _poly(px, py, V):
    d = min(_seg(px, py, *V[i], *V[(i + 1) % len(V)]) for i in range(len(V)))
    ins = False; j = len(V) - 1
    for i in range(len(V)):
        (xi, yi), (xj, yj) = V[i], V[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi: ins = not ins
        j = i
    return -d if ins else d
def _ngon(n, r, rot=0.0, r2=None):
    pts = []
    for i in range(n * (2 if r2 else 1)):
        a = rot - math.pi / 2 + i * math.pi * 2 / (n * (2 if r2 else 1))
        rr = r2 if (r2 and i % 2) else r; pts.append((rr * math.cos(a), rr * math.sin(a)))
    return pts
def _smin(a, b, k):
    h = max(0, min(1, .5 + .5 * (b - a) / k)); return b + (a - b) * h - k * h * (1 - h)

D = math.pi / 180
def sdf(shape):
    """Return f(x, y) -> signed distance, y down (screen coords)."""
    if shape == "circle": return lambda x, y: math.hypot(x, y) - 1
    if shape == "capsule":
        h = CAPSULE_H; L = 1.9 * h - h
        return lambda x, y: _seg(x, y, -L, 0, L, 0) - h
    if shape == "blob":   # wide squircle
        return lambda x, y: (abs(x / 1.18) ** 3.2 + abs(y / .86) ** 3.2) ** (1 / 3.2) - 1
    if shape == "diamond":   # rounded square, tilted
        def f(x, y):
            x, y = _rot(x, y, 18 * D); qx, qy = abs(x) - .62, abs(y) - .62
            return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - .28
        return f
    if shape == "sparkle":   # fat 4-point star
        V = _ngon(4, 1.0, 20 * D, .58); return lambda x, y: _poly(x, y, V) - .24
    if shape == "clover":
        C = [(.48 * math.cos(a), .48 * math.sin(a)) for a in (i * math.pi / 2 + 20 * D for i in range(4))]
        return lambda x, y: min(math.hypot(x - cx, y - cy) - .56 for cx, cy in C)
    if shape == "bean":   # tilted pill
        def f(x, y):
            x, y = _rot(x, y, -22 * D); return _seg(x, y, -.42, 0, .42, 0) - .72
        return f
    if shape == "scallop":
        C = [(.72 * math.cos(a), .72 * math.sin(a)) for a in (i * math.pi / 4 + 10 * D for i in range(8))]
        return lambda x, y: min(math.hypot(x, y) - .78, *(math.hypot(x - cx, y - cy) - .34 for cx, cy in C))
    if shape == "drop":   # egg with a soft point up and left
        ax, ay, r1 = .05, .14, .86; bx, by, r2 = -.42, -.72, .16
        def f(x, y):
            bax, bay = bx - ax, by - ay; ll = bax * bax + bay * bay
            h = max(0, min(1, ((x - ax) * bax + (y - ay) * bay) / ll))
            return math.hypot(x - ax - bax * h, y - ay - bay * h) - (r1 + (r2 - r1) * h)
        return f
    if shape == "triangle":
        V = _ngon(3, 1.05, 32 * D); return lambda x, y: _poly(x, y, V) - .3
    if shape == "house":   # pentagon, flat bottom
        V = _ngon(5, .96, -6 * D); return lambda x, y: _poly(x, y, V) - .22
    if shape == "star":   # spiky 8-point star
        V = _ngon(8, 1.22, 8 * D, .78); return lambda x, y: _poly(x, y, V) - .1
    if shape == "hexagon":
        V = _ngon(6, .94, 8 * D); return lambda x, y: _poly(x, y, V) - .16
    raise KeyError(shape)

def _radius(f, a, hi=3.0):
    c, s = math.cos(a), math.sin(a); lo = 0.0
    for _ in range(30):
        m = (lo + hi) / 2
        if f(m * c, m * s) < 0: lo = m
        else: hi = m
    return lo

_cache = {}
def series(shape):
    """Fourier coefficients of r(theta): [a0, (a1, b1), ..., (aK, bK)], equal-area normalized
    (capsule excepted), with a light Lanczos taper so sharp tips do not ring."""
    if shape in _cache: return _cache[shape]
    f0 = sdf(shape); N = SPEC_N
    # center the bounding box on the origin so every shape sits in the same spot
    r = [_radius(f0, i / N * 2 * math.pi) for i in range(N)]
    xs = [r[i] * math.cos(i / N * 2 * math.pi) for i in range(N)]; ys = [r[i] * math.sin(i / N * 2 * math.pi) for i in range(N)]
    ox, oy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    f = lambda x, y: f0(x + ox, y + oy)
    r = [_radius(f, i / N * 2 * math.pi) for i in range(N)]
    if shape != "capsule":
        area = sum(x * x for x in r) * math.pi / N; k = 1 / math.sqrt(area / math.pi); r = [x * k for x in r]
    a0 = sum(r) / N; co = []
    for m in range(1, HARM + 1):
        sig = math.sin(math.pi * m / (HARM + 1)) / (math.pi * m / (HARM + 1)) if m > 12 else 1.0
        a = sum(r[i] * math.cos(m * i / N * 2 * math.pi) for i in range(N)) * 2 / N
        b = sum(r[i] * math.sin(m * i / N * 2 * math.pi) for i in range(N)) * 2 / N
        co.append((a * sig, b * sig))
    _cache[shape] = (a0, co); return _cache[shape]

def radius(shape, a):
    a0, co = series(shape)
    return a0 + sum(c * math.cos((m + 1) * a) + s * math.sin((m + 1) * a) for m, (c, s) in enumerate(co))

def outline(shape, n=160):
    """(x, y, r) points around the outline in body units."""
    out = []
    for i in range(n):
        a = i / n * 2 * math.pi; r = radius(shape, a); out.append((r * math.cos(a), r * math.sin(a), r))
    return out

def extent(shape):
    pts = outline(shape, 128)
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))

# ---------- the saved choice ----------
CONFIG = os.path.expanduser(os.environ.get("NOVA_AVATAR_CFG", "~/.config/grokbot/avatar.json"))

def clean(d):
    d = d if isinstance(d, dict) else {}
    return {"shape": d.get("shape") if d.get("shape") in SHAPE_IDS else DEFAULT["shape"],
            "color": d.get("color") if d.get("color") in COLOR_IDS else DEFAULT["color"]}

def load(path=None):
    try:
        with open(path or CONFIG) as fh: return clean(json.load(fh))
    except (OSError, ValueError): return dict(DEFAULT)

def save(shape=None, color=None, path=None):
    """Merge and write atomically. Unknown ids raise ValueError."""
    path = path or CONFIG
    if shape is not None and shape not in SHAPE_IDS: raise ValueError("unknown shape")
    if color is not None and color not in COLOR_IDS: raise ValueError("unknown color")
    cur = load(path)
    if shape is not None: cur["shape"] = shape
    if color is not None: cur["color"] = color
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh: json.dump(cur, fh)
    os.replace(tmp, path); return cur
