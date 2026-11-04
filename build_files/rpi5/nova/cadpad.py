#!/usr/bin/env python3
"""Onshape pad for grokbotos (GTK3, app_id "nova-cadpad").

Big touch buttons for Onshape tools. Each tap sends a signed, named action over
the LAN to onshape-pad-helper on the CAD PC (Alpha), which presses the Onshape
keyboard shortcut there. Nothing is sent over USB.

Config:  /etc/grokbot/cadpad.conf, then ~/.config/grokbot/cadpad.conf (HOST=, PORT=)
Token:   ~/.config/grokbot/cadpad.token, mode 0600, never in the image
         (copy it with grokbot-cadpad-token; see docs/CADPAD.md).
Signing: X-Pad-Sig = hex HMAC-SHA256(token, METHOD\\nPATH\\nTIME\\nNONCE\\nBODY).

`cadpad.py --dump-actions` prints the helper's actions.json for this table.
Shortcuts are Onshape's defaults (cad.onshape.com/help glossary). Tools with no
default shortcut use Onshape's tool search (Alt+C, name, Enter) on the helper.
"""
import hashlib, hmac, json, os, re, secrets, stat, sys, threading, time, urllib.request, urllib.error

APP_ID = "nova-cadpad"
SYS_CONF = os.environ.get("CADPAD_SYS_CONF", "/etc/grokbot/cadpad.conf")
USER_CONF = os.path.expanduser(os.environ.get("CADPAD_USER_CONF", "~/.config/grokbot/cadpad.conf"))
TOKEN_FILE = os.path.expanduser(os.environ.get("CADPAD_TOKEN", "~/.config/grokbot/cadpad.token"))
DEFAULTS = {"HOST": "192.168.12.126", "PORT": "8790"}

# name: (label, keys) or (label, {"search": tool name})
ACTIONS = {
    # sketch
    "line": ("Line", ["l"]), "corner_rect": ("Corner rect", ["g"]), "center_rect": ("Center rect", ["r"]),
    "circle": ("Circle", ["c"]), "arc": ("3-pt arc", ["a"]), "sketch_point": ("Point", ["shift+s"]),
    "spline": ("Spline", {"search": "Spline"}), "slot": ("Slot", {"search": "Slot"}),
    "construction": ("Construction", ["q"]), "trim": ("Trim", ["m"]), "extend": ("Extend", ["x"]),
    "offset": ("Offset", ["o"]), "use": ("Use", ["u"]), "sketch_fillet": ("Fillet", ["shift+f"]),
    "sketch_mirror": ("Mirror", {"search": "Mirror"}), "dimension": ("Dimension", ["d"]),
    "coincident": ("Coincident", ["i"]), "horizontal": ("Horizontal", ["h"]), "vertical": ("Vertical", ["v"]),
    "parallel": ("Parallel", ["b"]), "perpendicular": ("Perpendicular", ["shift+l"]), "tangent": ("Tangent", ["t"]),
    "equal": ("Equal", ["e"]), "midpoint": ("Midpoint", ["shift+m"]), "concentric": ("Concentric", ["shift+o"]),
    "symmetric": ("Symmetric", ["shift+q"]), "fix": ("Fix", ["shift+j"]), "finish_extrude": ("Extrude", ["shift+e"]),
    # part studio
    "sketch": ("Sketch", ["shift+s"]), "extrude": ("Extrude", ["shift+e"]), "revolve": ("Revolve", ["shift+w"]),
    "fillet": ("Fillet", ["shift+f"]), "chamfer": ("Chamfer", {"search": "Chamfer"}), "shell": ("Shell", {"search": "Shell"}),
    "hole": ("Hole", {"search": "Hole"}), "mirror": ("Mirror", {"search": "Mirror"}),
    "linear_pattern": ("Linear pattern", {"search": "Linear pattern"}),
    "circular_pattern": ("Circular pattern", {"search": "Circular pattern"}),
    "plane": ("Plane", {"search": "Plane"}), "boolean": ("Boolean", {"search": "Boolean"}),
    "sweep": ("Sweep", {"search": "Sweep"}), "loft": ("Loft", {"search": "Loft"}), "draft": ("Draft", {"search": "Draft"}),
    "mate_connector": ("Mate connector", ["ctrl+m"]), "section": ("Section view", ["shift+x"]),
    "measure": ("Measure", ["bracketleft"]), "planes": ("Show planes", ["p"]), "sketches": ("Show sketches", ["shift+h"]),
    "hide_construction": ("Hide constr.", ["shift+p"]), "isolate": ("Isolate", ["shift+i"]),
    "transparent": ("Transparent", ["shift+t"]), "rename": ("Rename", ["shift+n"]),
    # assembly
    "insert": ("Insert", ["i"]), "mate": ("Mate", ["m"]), "group": ("Group", {"search": "Group"}),
    "show_mates": ("Show mates", ["j"]), "show_connectors": ("Show connectors", ["k"]), "mates_mode": ("Mates mode", ["h"]),
    "snap": ("Snap mode", ["shift+s"]), "flip_axis": ("Flip axis", ["a"]), "reorient_axis": ("Reorient axis", ["q"]),
    "copy": ("Copy", ["ctrl+c"]), "paste": ("Paste", ["ctrl+v"]), "hide": ("Hide", ["y"]), "show": ("Show", ["shift+y"]),
    # view
    "view_front": ("Front", ["shift+1"]), "view_back": ("Back", ["shift+2"]), "view_left": ("Left", ["shift+3"]),
    "view_right": ("Right", ["shift+4"]), "view_top": ("Top", ["shift+5"]), "view_bottom": ("Bottom", ["shift+6"]),
    "view_iso": ("Isometric", ["shift+7"]), "view_normal": ("Normal to", ["n"]), "zoom_fit": ("Zoom fit", ["f"]),
    "zoom_in": ("Zoom in", ["shift+z"]), "zoom_out": ("Zoom out", ["z"]), "zoom_window": ("Zoom window", ["w"]),
    "rot_up": ("Rotate ↑", ["Up"]), "rot_down": ("Rotate ↓", ["Down"]), "rot_left": ("Rotate ←", ["Left"]),
    "rot_right": ("Rotate →", ["Right"]), "tab_manager": ("Tabs", ["alt+t"]), "search_tools": ("Search tools", ["alt+c"]),
    "shortcut_toolbar": ("Shortcut bar", ["s"]), "clear_selection": ("Clear sel.", ["space"]), "delete": ("Delete", ["Delete"]),
    # common bar
    "undo": ("Undo", ["ctrl+z"]), "redo": ("Redo", ["ctrl+y"]), "escape": ("Esc", ["Escape"]),
    "accept": ("✓ Accept", ["Return"]), "accept_repeat": ("✓ + repeat", ["shift+Return"]),
}

PAGES = [
    ("Sketch", ["line", "corner_rect", "center_rect", "circle", "arc", "sketch_point",
                "spline", "slot", "construction", "trim", "extend", "offset",
                "use", "sketch_fillet", "sketch_mirror", "dimension", "coincident", "horizontal",
                "vertical", "parallel", "perpendicular", "tangent", "equal", "midpoint",
                "concentric", "symmetric", "fix", "finish_extrude"]),
    ("Part Studio", ["sketch", "extrude", "revolve", "fillet", "chamfer", "shell",
                     "hole", "mirror", "linear_pattern", "circular_pattern", "plane", "boolean",
                     "sweep", "loft", "draft", "mate_connector", "section", "measure",
                     "planes", "sketches", "hide_construction", "isolate", "transparent", "rename"]),
    ("Assembly", ["insert", "mate", "mate_connector", "group", "show_mates", "show_connectors",
                  "mates_mode", "snap", "flip_axis", "reorient_axis", "copy", "paste",
                  "hide", "show", "isolate", "transparent", "section", "measure"]),
    ("View", ["view_front", "view_back", "view_left", "view_right", "view_top", "view_bottom",
              "view_iso", "view_normal", "zoom_fit", "zoom_in", "zoom_out", "zoom_window",
              "rot_up", "rot_down", "rot_left", "rot_right", "tab_manager", "search_tools",
              "shortcut_toolbar", "clear_selection", "delete"]),
]
COMMON = ["undo", "redo", "escape", "accept", "accept_repeat"]
COLS = 6

def helper_actions():
    """actions.json for onshape-pad-helper (keys use xdotool names)."""
    out = {}
    for name, (_label, spec) in ACTIONS.items():
        out[name] = dict(spec) if isinstance(spec, dict) else {"keys": list(spec)}
    return {"actions": out}

# ---------- config, token, signing (no GTK; unit-tested) ----------
class PadError(Exception):
    pass

def read_conf(paths=None):
    c = dict(DEFAULTS)
    for p in paths or (SYS_CONF, USER_CONF):
        try:
            for line in open(p):
                m = re.match(r'^\s*(HOST|PORT)\s*=\s*"?([A-Za-z0-9.:-]+)"?\s*$', line)
                if m:
                    c[m.group(1)] = m.group(2)
        except OSError:
            pass
    if not re.match(r"^[0-9]{1,5}$", c["PORT"]) or not 0 < int(c["PORT"]) < 65536:
        c["PORT"] = DEFAULTS["PORT"]
    return c

def read_token(path=None):
    p = path or TOKEN_FILE
    try:
        st = os.stat(p)
    except FileNotFoundError:
        raise PadError("no token")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise PadError("token file must be 0600")
    t = open(p).read().strip()
    if not re.match(r"^[0-9a-f]{64}$", t):
        raise PadError("token looks wrong")
    return t.encode()

def sign(token, method, path, body, ts=None, nonce=None):
    ts = int(time.time()) if ts is None else int(ts)
    nonce = nonce or secrets.token_urlsafe(16)
    msg = b"\n".join([method.encode(), path.encode(), str(ts).encode(), nonce.encode(), body])
    return {"X-Pad-Time": str(ts), "X-Pad-Nonce": nonce,
            "X-Pad-Sig": hmac.new(token, msg, hashlib.sha256).hexdigest()}

class Client:
    def __init__(self, conf=None, token_path=None, timeout=3):
        self.conf = conf or read_conf(); self.token_path = token_path; self.timeout = timeout
        self.base = "http://%s:%s" % (self.conf["HOST"], self.conf["PORT"])
    def _req(self, method, path, body=b""):
        token = read_token(self.token_path)
        h = sign(token, method, path, body)
        if method == "POST":
            h["Content-Type"] = "application/json"
        rq = urllib.request.Request(self.base + path, data=body if method == "POST" else None, headers=h, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read() or b"{}")
            except ValueError:
                j = {}
            return {"ok": False, "error": j.get("error") or "HTTP %d" % e.code}
        except (urllib.error.URLError, OSError, ValueError):
            return {"ok": False, "error": "unreachable"}
    def health(self):
        try:
            return self._req("GET", "/health")
        except PadError as e:
            return {"ok": False, "error": str(e)}
    def press(self, action):
        if action not in ACTIONS:
            return {"ok": False, "error": "unknown action"}
        try:
            return self._req("POST", "/press", json.dumps({"action": action}).encode())
        except PadError as e:
            return {"ok": False, "error": str(e)}

def status_of(h):
    """green: helper + Onshape; yellow: helper up, Onshape closed; red: anything else."""
    if h.get("ok") and h.get("onshape_open"):
        return "green", "Onshape ready"
    if h.get("ok"):
        return "yellow", "Open Onshape on Alpha"
    return "red", {"no token": "No pad token yet", "unreachable": "Can't reach Alpha"}.get(h.get("error"), "Helper: %s" % h.get("error"))

# ---------- GTK UI ----------
CSS = b"""
window.cadpad { background: #000; }
#tabs button { font-size: 20px; padding: 10px 22px; border-radius: 22px; background: rgba(20,24,22,.7); background-image: none;
  color: #fff; border: 1px solid rgba(255,255,255,.18); box-shadow: none; text-shadow: none; }
#tabs button:checked { background: #14C370; color: #04140b; border-color: #14C370; font-weight: 700; }
button.tool { font-size: 18px; min-height: 64px; border-radius: 16px; background: rgba(20,24,22,.85); background-image: none;
  color: #d1fae5; border: 1px solid rgba(110,231,183,.18); box-shadow: none; text-shadow: none; }
button.tool:active, button.tool.hit { background: #14C370; color: #04140b; }
button.tool.err { background: #7f1d1d; color: #fff; }
button.tool.search label { font-style: italic; }
button.common { font-size: 18px; min-height: 56px; border-radius: 28px; background: rgba(255,255,255,.10); background-image: none;
  color: #fff; border: 1px solid rgba(255,255,255,.22); box-shadow: none; text-shadow: none; }
button#close { font-size: 18px; padding: 8px 18px; border-radius: 20px; background: rgba(255,255,255,.08); background-image: none;
  color: #fff; border: 1px solid rgba(255,255,255,.22); box-shadow: none; }
#status { color: rgba(255,255,255,.7); font-size: 15px; }
#last { color: #fcd34d; font-size: 15px; }
"""
DOT = {"green": (0.08, 0.76, 0.44), "yellow": (0.99, 0.83, 0.30), "red": (0.94, 0.27, 0.27), "grey": (0.5, 0.5, 0.5)}

def single_instance():
    """True if we are the only pad; otherwise focus the running one."""
    import fcntl
    run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    f = open(os.path.join(run, "nova-cadpad.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.system("swaymsg -q '[app_id=\"%s\"] focus, fullscreen enable' >/dev/null 2>&1" % APP_ID)
        return None
    return f

def run_gui(args):
    import gi
    gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
    from gi.repository import GLib
    GLib.set_prgname(APP_ID)
    from gi.repository import Gtk, Gdk
    client = Client()
    prov = Gtk.CssProvider(); prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
    win = Gtk.Window(title="Onshape pad"); win.get_style_context().add_class("cadpad")
    win.set_default_size(1280, 720); win.connect("destroy", Gtk.main_quit)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14); win.add(root)
    top = Gtk.Box(spacing=10); root.add(top)
    state = {"color": "grey"}
    dot = Gtk.DrawingArea(); dot.set_size_request(18, 18); dot.set_valign(Gtk.Align.CENTER)
    def draw_dot(w, cr):
        r, g, b = DOT[state["color"]]; cr.set_source_rgb(r, g, b)
        cr.arc(9, 9, 8, 0, 6.2832); cr.fill(); return False
    dot.connect("draw", draw_dot); top.add(dot)
    status = Gtk.Label(name="status", label="Checking Alpha…"); top.add(status)
    tabs = Gtk.Box(name="tabs", spacing=8, halign=Gtk.Align.CENTER, hexpand=True); top.add(tabs)
    close = Gtk.Button(label="✕ Close", name="close"); close.set_can_focus(False)
    close.connect("clicked", lambda *_: win.destroy()); top.add(close)
    stack = Gtk.Stack(vexpand=True); stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE); root.add(stack)
    last = Gtk.Label(name="last", label=""); root.add(last)

    def flash(btn, cls, ms=220):
        sc = btn.get_style_context(); sc.add_class(cls)
        GLib.timeout_add(ms, lambda: (sc.remove_class(cls), False)[1])
    def tap(btn, action):
        flash(btn, "hit")
        def work():
            r = client.press(action)
            def ui():
                if r.get("ok"):
                    last.set_text("")
                else:
                    flash(btn, "err", 600); last.set_text("%s: %s" % (ACTIONS[action][0], r.get("error")))
                return False
            GLib.idle_add(ui)
        threading.Thread(target=work, daemon=True).start()
    def make_btn(action, cls):
        label, spec = ACTIONS[action]
        b = Gtk.Button(label=label + (" …" if isinstance(spec, dict) else ""), hexpand=True)
        b.get_style_context().add_class(cls)
        if isinstance(spec, dict): b.get_style_context().add_class("search")
        b.set_can_focus(False); b.connect("clicked", tap, action); return b

    group = None
    for title, names in PAGES:
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True, row_homogeneous=True)
        for i, n in enumerate(names):
            grid.attach(make_btn(n, "tool"), i % COLS, i // COLS, 1, 1)
        stack.add_named(grid, title)
        t = Gtk.RadioButton.new_with_label_from_widget(group, title); group = group or t
        t.set_mode(False); t.set_can_focus(False)
        t.connect("toggled", lambda w, name=title: w.get_active() and stack.set_visible_child_name(name))
        tabs.add(t)
    bar = Gtk.Box(spacing=10, homogeneous=True); root.add(bar)
    for n in COMMON:
        bar.add(make_btn(n, "common"))

    def poll():
        def work():
            h = client.health()
            def ui():
                state["color"], text = status_of(h); status.set_text(text); dot.queue_draw(); return False
            GLib.idle_add(ui)
        threading.Thread(target=work, daemon=True).start()
        return True
    poll(); GLib.timeout_add_seconds(5, poll)
    if args.page:
        for c in tabs.get_children():
            if c.get_label() == args.page: c.set_active(True)
    win.show_all()
    if args.fullscreen: win.fullscreen()
    if args.quit_after: GLib.timeout_add(int(args.quit_after * 1000), lambda: (win.destroy(), False)[1])
    Gtk.main()

def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Onshape button pad (nova-cadpad)")
    p.add_argument("--dump-actions", action="store_true", help="print actions.json for onshape-pad-helper")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--page", choices=[t for t, _ in PAGES])
    p.add_argument("--quit-after", type=float, help="exit after N seconds (tests)")
    args = p.parse_args(argv)
    if args.dump_actions:
        print(json.dumps(helper_actions(), indent=1, ensure_ascii=False)); return 0
    lock = single_instance()
    if lock is None:
        return 0
    run_gui(args); return 0

if __name__ == "__main__":
    sys.exit(main())
