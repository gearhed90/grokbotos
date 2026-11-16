#!/usr/bin/env python3
"""Unit tests for the Pi 5 Nova pieces that do not need a display or root:
novad's key lookup order and checks, the nova-web prefs seeding, the lock scene (his apartment, asleep) and his
color (look.py). The flat avatar's own tests are archived with it in archive/avatar-v1/tests."""
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
                  NOVA_AVATAR_CFG=avatar_cfg, CYPHER_STATE_DIR=os.path.join(T, "state"), CYPHER_CONFIG_DIR=os.path.join(T, "ccfg"))
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

import json
import lockscene, look
s = lockscene.LockScene(rng=random.Random(1))
png = os.path.join(T, "lock.png"); lockscene.render_png(png, typed=4)
check("lock scene renders", os.path.getsize(png) > 10000)
s.W, s.H = 1280, 720
keys = {k: (x, y) for k, x, y, r in s.key_rects(1280, 720)}
check("keypad has 0-9, delete, ok", sorted(keys) == sorted(lockscene.KEYS))
check("hit test finds 5", s.hit(*keys["5"]) == "5")
check("hit test finds ok", s.hit(*keys["ok"]) == "ok")
check("left half (the room) is not a key", s.hit(200, 360) is None)
check("keypad sits on the right half", all(x > 640 for x, _ in keys.values()))
check("lock: he is asleep on the mattress", s.state == "sleeping" and s.ap.mv.spot == "bed" and s.ap.mv.pose == "lie", (s.ap.mv.spot, s.ap.mv.pose))
check("lock scene does not load the flat avatar", not any(m in sys.modules for m in ("avatar", "avatar_shapes", "glview")))
import cairo
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 360); c = cairo.Context(surf)
s.draw(c, 640, 360, now=0); b1 = s.bg[2]; s.draw(c, 640, 360, now=0)
check("lock room is drawn once per size (cached)", s.bg[2] is b1)
# ---------- his color (look.py; tints the placeholder body) ----------
check("11 colors, green default", len(look.COLOR_IDS) == 11 and look.load() == {"color": "green"})
c = look.save("teal")
check("save writes avatar.json (color only)", json.load(open(avatar_cfg)) == {"color": "teal"}, c)
try: look.save("nope"); check("unknown color raises", False)
except ValueError: check("unknown color raises", True)
open(avatar_cfg, "w").write("{not json")
check("broken avatar.json -> default", look.load() == look.DEFAULT)
open(avatar_cfg, "w").write(json.dumps({"shape": "hexagon", "color": "pink"}))
check("an old file's shape is ignored, its color kept", look.load() == {"color": "pink"})
r = novad.call_tool("set_color", {"color": "purple"})
check("novad set_color tool saves", r.get("ok") and look.load() == {"color": "purple"}, r)
check("novad set_color rejects unknown color", novad.call_tool("set_color", {"color": "pumpkin"}).get("ok") is False)
check("set_color in tool schema (color only)", any(t["function"]["name"] == "set_color" and list(t["function"]["parameters"]["properties"]) == ["color"]
                                       and t["function"]["parameters"]["properties"]["color"]["enum"] == look.COLOR_IDS for t in novad.tool_schema()))
check("no set_avatar (shape) tool any more", not any(t["function"]["name"] == "set_avatar" for t in novad.tool_schema()))
import apartment
check("apartment body takes his color", apartment.Apartment().tint == look.color_rgb("purple"))
check("novad does not load the flat avatar", not hasattr(novad, "avatar_shapes") and "avatar_shapes" not in sys.modules)
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
