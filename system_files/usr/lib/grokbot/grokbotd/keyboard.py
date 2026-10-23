"""keyboard.layout.*: the keyboard layout, without breaking Korean input.

Only layouts from LAYOUTS can be chosen (no free-form xkb strings reach
sway or fcitx5). Setting a layout does three things:
  1. sway: `input type:keyboard xkb_layout L xkb_variant V` (live), saved
     to ~/.config/grokbot/keyboard.conf, which /etc/sway/config includes;
  2. fcitx5: the user profile gets "Default Layout" = L and the keyboard
     engine keyboard-L[-V], with hangul kept as the second input method,
     so 한/영 keeps working; then `fcitx5-remote -r` reloads it;
  3. nothing else (no system-wide localectl change).
"""
import configparser
import os

from . import inputmethod, paths, procs, sway
from .backends import BackendError

# id: (xkb layout, xkb variant, ko, en)
LAYOUTS = {
    "us": ("us", "", "영어 (미국)", "English (US)"),
    "kr": ("kr", "kr104", "한국어 (106키, 한/영·한자 키)", "Korean (106-key, Han/Yeong and Hanja keys)"),
    "us-dvorak": ("us", "dvorak", "영어 (Dvorak)", "English (Dvorak)"),
    "us-colemak": ("us", "colemak", "영어 (Colemak)", "English (Colemak)"),
    "us-intl": ("us", "intl", "영어 (국제, 데드 키)", "English (international, dead keys)"),
    "gb": ("gb", "", "영어 (영국)", "English (UK)"),
    "de": ("de", "", "독일어", "German"),
    "fr": ("fr", "", "프랑스어", "French"),
    "es": ("es", "", "스페인어", "Spanish"),
    "it": ("it", "", "이탈리아어", "Italian"),
    "jp": ("jp", "", "일본어 (106키)", "Japanese (106-key)"),
}


def conf_path():
    return os.path.join(paths.config_home(), "grokbot", "keyboard.conf")


def profile_path():
    return os.path.join(paths.config_home(), "fcitx5", "profile")


def _engine(layout, variant):
    return "keyboard-%s" % layout + ("-%s" % variant if variant else "")


def saved():
    try:
        with open(conf_path(), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("# grokbot-layout: "):
                    lid = line.split(":", 1)[1].strip()
                    if lid in LAYOUTS:
                        return lid
    except OSError:
        pass
    return None


def _live():
    """(layout name sway reports, xkb layout names) of the first keyboard, or (None, [])."""
    try:
        inputs = sway.call(sway.GET_INPUTS)
    except sway.SwayUnavailable:
        return None, []
    for i in inputs or []:
        if i.get("type") == "keyboard":
            return i.get("xkb_active_layout_name"), i.get("xkb_layout_names") or []
    return None, []


def keyboard_layout_status(params):
    active, names = _live()
    _, ims = inputmethod._profile()
    return {"layout": saved() or "us", "active_name": active, "xkb_layout_names": names,
            "korean_input": "hangul" in ims, "input_methods": ims,
            "available": [{"id": k, "layout": v[0], "variant": v[1], "ko": v[2], "en": v[3]}
                          for k, v in LAYOUTS.items()]}


def _write_conf(lid, layout, variant):
    p = conf_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("# Written by grokbotd keyboard.layout.set (Settings > Keyboard).\n")
        fh.write("# grokbot-layout: %s\n" % lid)
        fh.write('input type:keyboard {\n    xkb_layout "%s"\n    xkb_variant "%s"\n}\n' % (layout, variant))
    os.replace(tmp, p)


def _write_profile(layout, variant):
    """User fcitx5 profile: chosen keyboard engine first, then every other
    configured method (hangul included) in the same order. Hangul is added if missing."""
    _, ims = inputmethod._profile()
    others = [m for m in ims if not m.startswith("keyboard-")]
    if "hangul" not in others:
        others.append("hangul")
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp["Groups/0"] = {"Name": "Default", "Default Layout": layout + ("-" + variant if variant else ""),
                      "DefaultIM": "hangul"}
    for n, name in enumerate([_engine(layout, variant)] + others):
        cp["Groups/0/Items/%d" % n] = {"Name": name, "Layout": ""}
    cp["GroupOrder"] = {"0": "Default"}
    p = profile_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        cp.write(fh, space_around_delimiters=False)
    os.replace(tmp, p)


def keyboard_layout_set(params):
    lid = params["layout"]
    if lid not in LAYOUTS:
        raise BackendError("unknown layout %r; see keyboard.layout.status available" % lid)
    layout, variant, _, _ = LAYOUTS[lid]
    cmd = 'input type:keyboard xkb_layout "%s"; input type:keyboard xkb_variant "%s"' % (layout, variant)
    try:
        res = sway.call(sway.RUN_COMMAND, cmd.encode())
    except sway.SwayUnavailable as e:
        raise BackendError("sway is not reachable: %s" % e)
    bad = [r.get("error") for r in res if not r.get("success")]
    if bad:
        raise BackendError("sway refused: %s" % "; ".join(str(b) for b in bad))
    _write_conf(lid, layout, variant)
    _write_profile(layout, variant)
    reloaded = False
    if procs.running("fcitx5"):
        reloaded = procs.run(["fcitx5-remote", "-r"]) is not None
    r = keyboard_layout_status({})
    r["fcitx5_reloaded"] = reloaded
    return r


METHODS = {
    "keyboard.layout.status": keyboard_layout_status,
    "keyboard.layout.set": keyboard_layout_set,
}
