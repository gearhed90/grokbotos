"""Cypher's color (build 16): the one piece of the retired flat avatar's look that stays. It tints his placeholder body
in the apartment until Zack approves his own design. set_avatar_color (cypherd) and novad's set_color tool / POST
/api/avatar write it; apartment.py reads it. The file keeps its old path and name (~/.config/grokbot/avatar.json),
so a color he already chose carries over; a leftover "shape" key is ignored. The shapes live in archive/avatar-v1."""
import json, os

COLORS = [
    ("white", "#FFFFFF"), ("brown", "#A8693A"), ("red", "#FF2D3D"), ("orange", "#FF6B1A"),
    ("amber", "#FF9F1A"), ("green", "#14C370"), ("teal", "#14B8A6"), ("blue", "#1E88FF"),
    ("purple", "#8B5CF6"), ("pink", "#FF3D8B"), ("gray", "#7A7A7A"),
]
COLOR_IDS = [c for c, _ in COLORS]
DEFAULT = {"color": "green"}
CONFIG = os.path.expanduser(os.environ.get("NOVA_AVATAR_CFG", "~/.config/grokbot/avatar.json"))

def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

def color_rgb(cid): return hex_rgb(dict(COLORS).get(cid, dict(COLORS)[DEFAULT["color"]]))

def clean(d):
    d = d if isinstance(d, dict) else {}
    return {"color": d.get("color") if d.get("color") in COLOR_IDS else DEFAULT["color"]}

def load(path=None):
    try:
        with open(path or CONFIG) as fh: return clean(json.load(fh))
    except (OSError, ValueError): return dict(DEFAULT)

def save(color, path=None):
    """Write atomically. An unknown id raises ValueError."""
    path = path or CONFIG
    if color not in COLOR_IDS: raise ValueError("unknown color")
    cur = {"color": color}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh: json.dump(cur, fh)
    os.replace(tmp, path); return cur
