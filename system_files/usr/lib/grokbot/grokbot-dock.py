#!/usr/bin/python3
"""Grok Bot OS dock: one layer-shell panel per enabled screen edge.

There are no desktop icons. The only app surfaces besides windows are
these docks and the fuzzel launcher.

Config (later files override earlier keys):
  /etc/grokbot/dock.conf
  ~/.config/grokbot/dock.conf   (written by grokbot-dock-config)

  [dock]
  top = off | icons
  bottom = off | icons
  left = off | icons | labels
  right = off | icons | labels
  icon_size = 40
  hide = footclient.desktop;foot-server.desktop

top/bottom are icon-only: "labels" there is treated as "icons".
SIGHUP (or grokbot-dock-config) reloads the config.
"""
import configparser
import json
import os
import shlex
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gio, GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

GROKBOT_DESKTOP = "grok-bot.desktop"
GROKBOT_APP_ID = "grok-bot"
EDGES = ("top", "bottom", "left", "right")
SYS_CONF = os.environ.get("GROKBOT_DOCK_SYS_CONF", "/etc/grokbot/dock.conf")
USER_CONF = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "grokbot", "dock.conf")

CSS = b"""
window.grokbot-dock { background-color: rgba(24,24,27,0.94); }
.grokbot-dock button { background: none; border: none; box-shadow: none;
  padding: 4px; margin: 2px; border-radius: 10px; color: #f4f4f5; }
.grokbot-dock button:hover { background-color: rgba(255,255,255,0.10); }
.grokbot-dock button.focused { background-color: rgba(255,255,255,0.18); }
.grokbot-dock .dot { color: rgba(0,0,0,0); font-size: 8px; }
.grokbot-dock button.running .dot { color: #60a5fa; }
.grokbot-dock label.name { padding-left: 8px; padding-right: 8px; }
"""


def load_config():
    cp = configparser.ConfigParser()
    cp.read([SYS_CONF, USER_CONF])
    d = cp["dock"] if cp.has_section("dock") else {}
    conf = {}
    for e in EDGES:
        v = str(d.get(e, "icons" if e == "bottom" else "off")).strip().lower()
        if v not in ("off", "icons", "labels"):
            v = "off"
        if e in ("top", "bottom") and v == "labels":
            v = "icons"
        conf[e] = v
    try:
        conf["icon_size"] = max(16, min(96, int(d.get("icon_size", "40"))))
    except ValueError:
        conf["icon_size"] = 40
    conf["hide"] = {h.strip() for h in
                    str(d.get("hide", "footclient.desktop;foot-server.desktop")).split(";")
                    if h.strip()}
    return conf


def swaymsg(*args):
    try:
        out = subprocess.run(["swaymsg", "-r", *args], capture_output=True,
                             text=True, timeout=5)
        return out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def views(node, acc):
    if node.get("type") in ("con", "floating_con") and node.get("pid") \
            and not node.get("nodes") and not node.get("floating_nodes"):
        acc.append(node)
    for k in ("nodes", "floating_nodes"):
        for c in node.get(k, []):
            views(c, acc)
    return acc


def window_key(v):
    app_id = v.get("app_id")
    if not app_id:
        app_id = (v.get("window_properties") or {}).get("class") or ""
    return app_id.lower()


def app_keys(info):
    keys = set()
    did = (info.get_id() or "").lower()
    if did.endswith(".desktop"):
        did = did[:-8]
    if did:
        keys.add(did)
        keys.add(did.split(".")[-1])
    wm = info.get_string("StartupWMClass") if hasattr(info, "get_string") else None
    if wm:
        keys.add(wm.lower())
    exe = info.get_executable() or ""
    if exe:
        keys.add(os.path.basename(exe).lower())
    if info.get_id() == GROKBOT_DESKTOP:
        keys.add(GROKBOT_APP_ID)
    return keys


def app_list(hide):
    apps = [a for a in Gio.AppInfo.get_all()
            if a.should_show() and a.get_id() not in hide]
    apps.sort(key=lambda a: (a.get_id() != GROKBOT_DESKTOP,
                             (a.get_display_name() or "").lower()))
    if not any(a.get_id() == GROKBOT_DESKTOP for a in apps):
        g = Gio.DesktopAppInfo.new(GROKBOT_DESKTOP)
        if g is not None:
            apps.insert(0, g)
    return apps


def new_workspace():
    try:
        wss = json.loads(swaymsg("-t", "get_workspaces") or "[]")
    except ValueError:
        wss = []
    used = {w.get("num") for w in wss}
    n = 2
    while n in used:
        n += 1
    return n


def launch(info):
    if info.get_id() == GROKBOT_DESKTOP:
        # grokbot-kiosk keeps Grok Bot running on workspace 1.
        swaymsg("workspace number 1")
        return
    cmd = "gtk-launch " + shlex.quote(info.get_id()[:-8] if info.get_id().endswith(".desktop") else info.get_id())
    # sway puts windows from `exec` on the workspace that was focused
    # when exec ran, so each app opens alone and fills the usable area.
    swaymsg(f"workspace number {new_workspace()}; exec {cmd}")


class Dock:
    def __init__(self):
        self.windows = {}
        self.buttons = []  # (button, keys, info)
        self.conf = load_config()
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self.rebuild())
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        add_signal = getattr(GLib, "unix_signal_add")
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGHUP, self.reload)
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        self.rebuild()
        GLib.timeout_add(1500, self.refresh)

    def quit(self):
        Gtk.main_quit()
        return False

    def reload(self):
        self.conf = load_config()
        self.rebuild()
        return True

    def rebuild(self):
        for w in self.windows.values():
            w.destroy()
        self.windows = {}
        self.buttons = []
        apps = app_list(self.conf["hide"])
        for edge in EDGES:
            mode = self.conf[edge]
            if mode != "off":
                self.windows[edge] = self.make_window(edge, mode, apps)
        self.refresh()

    def make_window(self, edge, mode, apps):
        win = Gtk.Window()
        win.get_style_context().add_class("grokbot-dock")
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "grokbot-dock")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
        e = {"top": GtkLayerShell.Edge.TOP, "bottom": GtkLayerShell.Edge.BOTTOM,
             "left": GtkLayerShell.Edge.LEFT, "right": GtkLayerShell.Edge.RIGHT}
        GtkLayerShell.set_anchor(win, e[edge], True)
        horiz = edge in ("top", "bottom")
        # Stretch along the edge.
        for other in (("left", "right") if horiz else ("top", "bottom")):
            GtkLayerShell.set_anchor(win, e[other], True)
        GtkLayerShell.auto_exclusive_zone_enable(win)
        orient = Gtk.Orientation.HORIZONTAL if horiz else Gtk.Orientation.VERTICAL
        box = Gtk.Box(orientation=orient, spacing=0)
        box.set_halign(Gtk.Align.CENTER if horiz else Gtk.Align.FILL)
        box.set_valign(Gtk.Align.CENTER if not horiz else Gtk.Align.FILL)
        if not horiz:
            box.set_valign(Gtk.Align.START)
            box.set_margin_top(6)
        size = self.conf["icon_size"]
        for info in apps:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            name = info.get_display_name() or info.get_id()
            btn.set_tooltip_text(name)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if horiz
                            else Gtk.Orientation.HORIZONTAL)
            img = Gtk.Image()
            icon = info.get_icon()
            if icon is not None:
                img.set_from_gicon(icon, Gtk.IconSize.DIALOG)
            else:
                img.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
            img.set_pixel_size(size)
            dot = Gtk.Label(label="●")
            dot.get_style_context().add_class("dot")
            if horiz:
                inner.pack_start(img, False, False, 0)
                inner.pack_start(dot, False, False, 0)
            else:
                inner.pack_start(dot, False, False, 0)
                inner.pack_start(img, False, False, 0)
                if mode == "labels":
                    lab = Gtk.Label(label=name, xalign=0)
                    lab.get_style_context().add_class("name")
                    # Without a width request GTK shrinks an ellipsizing
                    # label to just "...".
                    lab.set_width_chars(14)
                    lab.set_max_width_chars(18)
                    lab.set_ellipsize(3)  # Pango.EllipsizeMode.END
                    inner.pack_start(lab, True, True, 0)
            btn.add(inner)
            btn.connect("clicked", self.on_click, info)
            box.pack_start(btn, False, False, 0)
            self.buttons.append((btn, app_keys(info), info))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC if horiz else Gtk.PolicyType.NEVER,
                            Gtk.PolicyType.NEVER if horiz else Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_width(True)
        scroller.set_propagate_natural_height(True)
        scroller.add(box)
        win.add(scroller)
        win.show_all()
        return win

    def current_views(self):
        try:
            return views(json.loads(swaymsg("-t", "get_tree") or "{}"), [])
        except ValueError:
            return []

    def on_click(self, _btn, info):
        keys = app_keys(info)
        for v in self.current_views():
            if window_key(v) in keys:
                swaymsg(f"[con_id={v['id']}] focus")
                return
        launch(info)

    def refresh(self):
        vs = self.current_views()
        running = {window_key(v) for v in vs}
        focused = {window_key(v) for v in vs if v.get("focused")}
        for btn, keys, _info in self.buttons:
            ctx = btn.get_style_context()
            for cls, on in (("running", bool(keys & running)),
                            ("focused", bool(keys & focused))):
                if on:
                    ctx.add_class(cls)
                else:
                    ctx.remove_class(cls)
        return True


def main():
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("grokbot-dock: WAYLAND_DISPLAY is not set", file=sys.stderr)
        return 1
    Dock()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
