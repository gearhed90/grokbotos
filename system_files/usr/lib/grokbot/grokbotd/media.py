"""audio.status and display.brightness (read-only)."""
import glob
import os

from . import paths, procs


def _volume(target):
    out = procs.run(["wpctl", "get-volume", target])
    if out is None or not out.startswith("Volume:"):
        return None
    parts = out.split()
    try:
        vol = float(parts[1])
    except (IndexError, ValueError):
        return None
    return {"volume_percent": int(round(vol * 100)), "muted": "[MUTED]" in out}


def audio_status(params):
    out = _volume("@DEFAULT_AUDIO_SINK@")
    inp = _volume("@DEFAULT_AUDIO_SOURCE@")
    return {"available": out is not None, "output": out, "input": inp}


def _int(path):
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def display_brightness(params):
    devs = []
    for d in sorted(glob.glob(os.path.join(paths.sysfs(), "class", "backlight", "*"))):
        cur, mx = _int(os.path.join(d, "brightness")), _int(os.path.join(d, "max_brightness"))
        if cur is None or not mx:
            continue
        devs.append({"name": os.path.basename(d), "brightness": cur, "max_brightness": mx,
                     "percent": int(round(cur * 100 / mx))})
    return {"available": bool(devs), "devices": devs}
