#!/usr/bin/env python3
"""Unit tests for the Pi 5 Nova pieces that do not need a display or root:
novad's key lookup order and checks, the nova-web prefs seeding, and the lock scene."""
import os, sys, tempfile, importlib.util, random
HERE = os.path.dirname(os.path.abspath(__file__))
NOVA = os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "nova")
sys.path.insert(0, NOVA)
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:200]))

T = tempfile.mkdtemp()
user_key = os.path.join(T, "user_key"); sys_key = os.path.join(T, "sys_key")
avatar_cfg = os.path.join(T, "cfg", "avatar.json")
os.environ.update(NOVA_KEY_FILE=user_key, NOVA_SYS_KEY_FILE=sys_key, NOVA_WEB_USERJS=os.path.join(NOVA, "nova-web-user.js"),
                  NOVA_AVATAR_CFG=avatar_cfg)
spec = importlib.util.spec_from_file_location("novad", os.path.join(NOVA, "novad.py"))
novad = importlib.util.module_from_spec(spec); spec.loader.exec_module(novad)

def err(f):
    try:
        f(); return None
    except novad.KeyError_ as e:
        return str(e)

check("no key anywhere -> nokey", err(novad.read_key) == "nokey")
check("health reports no key", novad.key_present() is False)
open(user_key, "w").write("user-test-key\n"); os.chmod(user_key, 0o644)
check("world-readable user key refused", err(novad.read_key) == "badperm")
os.chmod(user_key, 0o600)
check("user key used when no system key", novad.read_key() == "user-test-key")
open(sys_key, "w").write("sys-test-key\n"); os.chmod(sys_key, 0o640)
# Not root-owned (the test runs as a normal user), so it must be refused, not used.
if os.getuid() != 0:
    check("system key not owned by root is refused", err(novad.read_key) == "badsys")
novad.SYS_KEY_FILE = ""
check("empty NOVA_SYS_KEY_FILE disables the system key", novad.read_key() == "user-test-key")
novad.SYS_KEY_FILE = os.path.join(T, "missing")
check("missing system key falls back to user key", novad.read_key() == "user-test-key")

prof = os.path.join(T, "prof"); os.makedirs(prof)
novad.seed_web_profile(prof)
data = open(os.path.join(prof, "user.js")).read()
check("nova-web user.js seeded", 'media.ffmpeg.enabled", true' in data and "sessionstore.resume_from_crash" in data)
check("nova-web does not enable openh264 download", 'gmpopenh264.enabled", false' in data)

import lockscene
s = lockscene.LockScene(rng=random.Random(1))
png = os.path.join(T, "lock.png"); lockscene.render_png(png, typed=4)
check("lock scene renders", os.path.getsize(png) > 10000)
s.W, s.H = 1280, 720
keys = {k: (x, y) for k, x, y, r in s.key_rects(1280, 720)}
check("keypad has 0-9, delete, ok", sorted(keys) == sorted(lockscene.KEYS))
check("hit test finds 5", s.hit(*keys["5"]) == "5")
check("hit test finds ok", s.hit(*keys["ok"]) == "ok")
check("left half (avatar) is not a key", s.hit(200, 360) is None)
check("keypad sits on the right half", all(x > 640 for x, _ in keys.values()))
check("avatar is asleep", s.av.state == "sleeping")
# ---------- avatar shapes and colors ----------
import math, json, cairo
import avatar_shapes as AS
from avatar import Avatar, STATES
check("13 shapes, 11 colors", len(AS.SHAPE_IDS) == 13 and len(AS.COLOR_IDS) == 11, (len(AS.SHAPE_IDS), len(AS.COLOR_IDS)))
check("default look is the original green capsule", AS.DEFAULT == {"shape": "capsule", "color": "green"})
check("no config -> default", AS.load() == AS.DEFAULT)
check("orange is FF6B1A", AS.color_rgb("orange") == (1.0, 0x6B / 255, 0x1A / 255))
worst = {}
for sh in AS.SHAPE_IDS:
    f = AS.sdf(sh); a0, co = AS.series(sh)
    pts = AS.outline(sh, 96)
    # the series is centred and, apart from the capsule, has the area of the unit circle
    area = sum(r * r for _, _, r in pts) * math.pi / len(pts)
    x0, y0, x1, y1 = AS.extent(sh)
    worst[sh] = (round(area, 3), round(abs(x0 + x1) + abs(y0 + y1), 3))
check("every shape has 32 harmonics", all(len(AS.series(s)[1]) == AS.HARM for s in AS.SHAPE_IDS))
check("shapes have equal area", all(abs(worst[s][0] - math.pi) < .08 for s in AS.SHAPE_IDS if s != "capsule"), worst)
check("shapes are centred", all(worst[s][1] < .08 for s in AS.SHAPE_IDS), worst)
check("outline radius always positive", all(r > .2 for s in AS.SHAPE_IDS for _, _, r in AS.outline(s, 256)))

def px(surf, x, y):
    d = surf.get_data(); st = surf.get_stride(); i = int(y) * st + int(x) * 4
    return d[i + 2], d[i + 1], d[i]
W, H = 640, 360
eyes_ok, body_ok, states_ok = [], [], []
for sh in AS.SHAPE_IDS:
    for cid in ("orange", "white", "amber", "gray"):
        av = Avatar(rng=random.Random(3), style={"shape": sh, "color": cid}); av.forceBlink = 1
        av.set_state("idle"); av.simulate(1.0); av.tick(.02)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H); av.draw(cairo.Context(surf), W, H)
        h0 = H * av.lay["h"]; g = av.geom(h0, 0, h0 / 2, 0); cx, cy = W * av.lay["cx"], H * av.lay["cy"]
        want = tuple(round(c * 255) for c in AS.color_rgb(cid))
        # body colour shows between the eyes and the top edge; the eyes stay dark on every color
        bx, by = cx + g["ecx"], cy + g["ecy"] - h0 * .3 * g["es"]
        body_ok.append(sum(abs(a - b) for a, b in zip(px(surf, bx, by), want)) < 40 or (sh, cid, px(surf, bx, by), want))
        ex = cx + g["ecx"] + h0 * .25 * g["es"] + av.G("lx") * h0 * .272 * g["mv"]; ey = cy + g["ecy"] + av.G("ly") * h0 * .3 * g["mv"]
        eyes_ok.append(max(px(surf, ex, ey)) < 40 or (sh, cid, px(surf, ex, ey)))
    for st in STATES:
        av = Avatar(rng=random.Random(4), style={"shape": sh, "color": "blue"}); av.set_state(st); av.simulate(1.5)
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 320, 180); c = cairo.Context(surf)
        for _ in range(5): av.tick(.03); av.draw(c, 320, 180)
        states_ok.append(any(max(px(surf, x, y)) > 100 for x in range(0, 320, 4) for y in range(0, 180, 4)) or (sh, st))
check("body shows the chosen color, every shape", all(x is True for x in body_ok), [x for x in body_ok if x is not True])
check("eyes are dark on every shape and color", all(x is True for x in eyes_ok), [x for x in eyes_ok if x is not True])
check("every state draws on every shape", all(x is True for x in states_ok), [x for x in states_ok if x is not True])
av = Avatar(style={"shape": "star", "color": "pink"})
check("set_style switches live", av.set_style(shape="circle")["shape"] == "circle" and av.style["color"] == "pink")
check("unknown shape falls back", Avatar(style={"shape": "pumpkin"}).style["shape"] == AS.DEFAULT["shape"])

c = AS.save(shape="star")
check("save writes avatar.json", json.load(open(avatar_cfg)) == {"shape": "star", "color": "green"}, c)
AS.save(color="teal")
check("save merges shape and color", AS.load() == {"shape": "star", "color": "teal"})
for bad in ({"shape": "pumpkin"}, {"color": "#123456"}):
    try: AS.save(**bad); check("save rejects " + str(bad), False)
    except ValueError: check("save rejects " + str(bad), True)
open(avatar_cfg, "w").write("{not json")
check("broken avatar.json -> default", AS.load() == AS.DEFAULT)
open(avatar_cfg, "w").write(json.dumps({"shape": "hexagon", "color": "nope"}))
check("bad color in file -> default color, shape kept", AS.load() == {"shape": "hexagon", "color": AS.DEFAULT["color"]})

r = novad.call_tool("set_avatar", {"shape": "drop", "color": "purple"})
check("novad set_avatar tool saves", r.get("ok") and AS.load() == {"shape": "drop", "color": "purple"}, r)
check("novad set_avatar rejects unknown shape", novad.call_tool("set_avatar", {"shape": "pumpkin"}).get("ok") is False)
check("set_avatar in tool schema", any(t["function"]["name"] == "set_avatar" and t["function"]["parameters"]["properties"]["shape"]["enum"] == AS.SHAPE_IDS
                                       for t in novad.tool_schema()))
check("lock scene uses the saved look", lockscene.LockScene(rng=random.Random(1)).av.style == {"shape": "drop", "color": "purple"})
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
