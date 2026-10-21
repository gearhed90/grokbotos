"""input.status: keyboard input method (fcitx5) state (read-only)."""
import configparser
import os

from . import paths, procs


def _profile():
    for p in (os.path.join(paths.config_home(), "fcitx5", "profile"),
              os.environ.get("GROKBOT_FCITX_SYS_PROFILE") or "/etc/xdg/fcitx5/profile"):
        if os.path.isfile(p):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            try:
                cp.read(p, encoding="utf-8")
            except configparser.Error:
                continue
            ims = [cp[s].get("Name") for s in cp.sections()
                   if s.startswith("Groups/0/Items/") and cp[s].get("Name")]
            return p, ims
    return None, []


def _triggers():
    for p in (os.path.join(paths.config_home(), "fcitx5", "config"),
              os.environ.get("GROKBOT_FCITX_SYS_CONFIG") or "/etc/xdg/fcitx5/config"):
        if os.path.isfile(p):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            try:
                cp.read(p, encoding="utf-8")
            except configparser.Error:
                continue
            if cp.has_section("Hotkey/TriggerKeys"):
                return [v for _k, v in sorted(cp["Hotkey/TriggerKeys"].items())]
    return []


def input_status(params):
    running = procs.running("fcitx5")
    current = active = None
    if running:
        current = (procs.run(["fcitx5-remote", "-n"]) or "").strip() or None
        state = (procs.run(["fcitx5-remote"]) or "").strip()
        active = {"2": True, "1": False}.get(state)
    profile, ims = _profile()
    return {"framework": "fcitx5", "running": running, "current": current,
            "active": active, "input_methods": ims, "trigger_keys": _triggers(),
            "profile": profile, "xmodifiers": os.environ.get("XMODIFIERS")}
