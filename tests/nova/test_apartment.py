#!/usr/bin/env python3
"""Build 16: Cypher's apartment (apartment.py, apartment_gl.py). No display, root or network: the scene, the spots,
walking between them, leaving through the door, the swappable body asset, idle frame rate, and a headless PNG.
The GLES path is checked offscreen (EGL surfaceless) only where a GPU is available; otherwise it is skipped."""
import json, math, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NOVA = os.path.join(ROOT, "build_files", "rpi5", "nova")
sys.path.insert(0, NOVA)
T = tempfile.mkdtemp()
os.environ["NOVA_AVATAR_CFG"] = os.path.join(T, "avatar.json")
os.environ["CYPHER_CONFIG_DIR"] = os.path.join(T, "cfg")
import apartment as A
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:400]))

dp, wp = os.path.join(T, "dash.json"), os.path.join(T, "world.json")
def dash(**k):
    json.dump(k, open(dp, "w")); st = os.stat(dp); os.utime(dp, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
json.dump({"weather": "a soft drizzle, warm neon"}, open(wp, "w"))
dash(spot="window", mood={"label": "content", "valence": 0.2, "arousal": 0.1})

# ---- the room matches his description ----
room = A.build_room()
check("one room: a few thousand triangles at most", 200 < len(room.quads) * 2 < 6000, len(room.quads))
src = open(os.path.join(NOVA, "apartment.py")).read()
check("built from his own words (quoted in the module)", "Mattress on the floor, cables snaking to a crate that holds the deck" in src)
check("window with blinds, mattress, crate+deck, cables, sink + noodle cups, grid conduit, door",
      all(w in src for w in ("blind slats", "mattress on the floor", "the crate that holds the deck", "cables snaking", "noodle cups", "grid humming", "the door")))
check("no Pino text or art in the scene (original geometry only)", "pinos.world" not in src.lower() and not any(f.endswith((".glb", ".gltf", ".png")) for f in os.listdir(NOVA)))

# ---- the spots ----
check("every spot is inside the room", all(-2.5 < s[0] < 2.5 and -2.0 < s[1] < 2.0 for s in A.SPOTS.values()))
for d, want in (({"activity": "reading about Arasaka", "place": "apartment"}, "desk"), ({"activity": "resting"}, "bed"),
                ({"activity": "out in Night City", "place": "noodle stall"}, "out"), ({"activity": "thinking"}, "window"),
                ({"activity": "eating noodles"}, "sink"), ({"activity": "standing by: Alpha holds the mind", "active": False}, "out"),
                ({"spot": "desk", "activity": "resting"}, "desk")):
    check("spot_from_dash %s -> %s" % (d.get("activity") or d.get("spot"), want), A.spot_from_dash(d) == want, A.spot_from_dash(d))

def run(mv, sec, dt=1 / 30):
    for _ in range(int(sec / dt)): mv.tick(dt)

mv = A.Mover("window")
check("starts standing at the window", mv.pose == "stand" and abs(mv.x - A.SPOTS["window"][0]) < 1e-6 and mv.alpha == 1.0)
mv.go("desk"); run(mv, 8)
check("walks to the desk terminal and sits", not mv.busy() and mv.pose == "sit" and math.hypot(mv.x - A.SPOTS["desk"][0], mv.z - A.SPOTS["desk"][1]) < 0.02, (mv.x, mv.z, mv.pose))
mv.go("bed"); run(mv, 10)
check("gets up, walks over and lies on the mattress", not mv.busy() and mv.pose == "lie", (mv.pose, mv.phase))
fq = A.figure_quads(A.body_quads(A.PLACEHOLDER, (0, 1, 0)), mv, A.scene_env(), A.room_lights(A.scene_env()))
ys = [p[1] for q in fq for p in q[:4]]; xs = [p[0] for q in fq for p in q[:4]]
check("lying: on top of the mattress, inside its length", min(ys) > 0.2 and max(ys) < 0.7 and 0.4 < min(xs) and max(xs) < 2.45, (min(ys), max(ys), min(xs), max(xs)))
mv.go("out"); run(mv, 12)
check("going out: walks to the door and fades away", mv.alpha == 0.0 and not mv.busy() and math.hypot(mv.x - A.SPOTS["door"][0], mv.z - A.SPOTS["door"][1]) < 0.02)
check("no figure drawn while out", A.figure_quads(A.body_quads(A.PLACEHOLDER, (0, 1, 0)), mv, A.scene_env(), []) == [])
mv.go("window"); run(mv, 0.2)
check("coming back: appears at the door", 0 < mv.alpha < 1 and mv.x > 1.5)
run(mv, 10)
check("...and walks to the window", not mv.busy() and mv.alpha == 1.0 and abs(mv.x - A.SPOTS["window"][0]) < 0.02)
# path never crosses the mattress or the crate
mv = A.Mover("desk"); mv.go("bed"); pts = []
for _ in range(400): mv.tick(1 / 30); pts.append((mv.x, mv.z))
check("walk path stays clear of the crate and mattress", not any((0.40 < x < 2.42 and -1.98 < z < -0.92) or (-2.15 < x < -1.55 and -0.95 < z < -0.35) for x, z in pts))

# ---- the scene object ----
ap = A.Apartment(dash_path=dp, world_path=wp)
check("starts at the snapshot's spot", ap.mv.spot == "window")
check("idle: modest frame rate (<=12 fps)", ap.frame_interval() >= 1 / 12 - 1e-9, ap.frame_interval())
dash(spot="desk", mood={"label": "curious", "valence": 0.4, "arousal": 0.6})
ap.tick(1.1)
check("new snapshot -> walks to the new spot at 30 fps", ap.mv.spot == "desk" and ap.frame_interval() == A.Apartment.WALK_FRAME)
v0 = ap.version; ap.simulate(8)
check("the deck screen lights up while he works there (relight once)", ap.env["desk_on"] and ap.version > v0)
ap.set_state("listening"); check("Zack talking -> attention", ap.mv.attention)
ap.set_state("sleeping"); check("the screen dozing is not his sleep", not ap.mv.attention and ap.mv.spot == "desk")
dash(spot="out", place="noodle stall"); ap.tick(1.1); ap.simulate(12)
check("caption while out", ap.caption().startswith("Out in Night City") and "noodle stall" in ap.caption(), ap.caption())
check("out: 8 fps", ap.frame_interval() == A.Apartment.NIGHT_FRAME)
dash(spot="bed", quiet=True); ap.tick(1.1); ap.simulate(14)
check("quiet hours in bed: room dims, bulb off", ap.env["bulb"] == 0 and ap.env["ambient"][0] < 0.16, ap.env)
op, dec, glow = ap.room_vertices()
check("GL buffers: 10 floats a vertex, whole triangles", len(op) % 30 == 0 and len(dec) % 30 == 0 and op and glow)

# ---- the body is one swappable asset ----
b, p = A.load_body([os.path.join(NOVA, "apartment_body_placeholder.json")])
check("the shipped placeholder loads and says it is temporary", b.get("temporary") is True and len(b["parts"]) >= 6 and p)
bad = os.path.join(T, "bad.json"); open(bad, "w").write("{not json")
new = os.path.join(T, "body.json")
json.dump({"name": "his design", "temporary": False, "parts": [{"box": [-0.3, 0, -0.2, 0.3, 1.9, 0.2], "color": "#ff2a6d"}]}, open(new, "w"))
b2, p2 = A.load_body([bad, new])
check("a broken file falls through; the next asset is used", b2["name"] == "his design" and p2 == new)
b3, p3 = A.load_body([bad])
check("nothing valid -> built-in placeholder", b3["name"] == "placeholder" and p3 is None)
ap2 = A.Apartment(dash_path=dp, world_path=wp, body_paths=[new]); ap2.simulate(1)
check("swapping the asset changes the figure, nothing else", len(ap2.bq) == 1 and ap2.bq[0][2] == A.hexrgb("ff2a6d"))
check("the image ships the approved-body path", "/usr/share/grokbot/cypher/apartment/body.json" in A.BODY_PATHS)

# ---- headless render ----
png = os.path.join(T, "room.png")
ap3 = A.render_png(png, (640, 360), {"mood": {"valence": 0.2, "arousal": 0.1}}, {"weather": "rain"}, "window")
check("headless PNG renders", os.path.getsize(png) > 10000 and ap3.mv.spot == "window")
try:
    import cairo
    s = cairo.ImageSurface.create_from_png(png); data = bytes(s.get_data()); W, H, st = s.get_width(), s.get_height(), s.get_stride()
    def px(x, y): o = y * st + x * 4; return data[o + 2], data[o + 1], data[o]
    check("the room is not black", sum(sum(px(x, y)) for x in range(0, W, 16) for y in range(0, H, 16)) > 20 * (W // 16) * (H // 16))
except Exception as e:
    check("PNG readable", False, e)

# ---- GLES offscreen (only where EGL + a GPU exist) ----
gl_src = open(os.path.join(NOVA, "apartment_gl.py")).read()
check("GL renderer: depth test, static room VBO, per-frame figure only", "GL_DEPTH_TEST" in gl_src and "GL_STATIC_DRAW" in gl_src and '"fig"' in gl_src)
if os.environ.get("APT_GL_TEST") == "1":
    import apartment_gl as AG
    out = os.path.join(T, "gl.png")
    ap4 = A.Apartment(dash_path=dp, world_path=wp); ap4.simulate(2)
    try:
        info = AG.offscreen_png(out, ap4, 320, 180)
        check("GLES offscreen render (%s)" % (info[0].decode() if info else "?"), os.path.getsize(out) > 2000)
    except Exception as e:
        check("GLES offscreen render", False, e)
else:
    print("SKIP GLES offscreen (set APT_GL_TEST=1 on a machine with a GPU)")

print("%d passed, %d failed" % (ok, fail))
sys.exit(1 if fail else 0)
