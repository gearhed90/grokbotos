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
os.environ.update(NOVA_KEY_FILE=user_key, NOVA_SYS_KEY_FILE=sys_key, NOVA_WEB_USERJS=os.path.join(NOVA, "nova-web-user.js"))
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
print("\n%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
