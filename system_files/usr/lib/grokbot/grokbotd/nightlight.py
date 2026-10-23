"""display.nightlight.status / display.nightlight.set: warmer screen colours at
night (gammastep, wlr-gamma-control on sway).

Settings live in ~/.config/grokbot/nightlight.json. The user unit
grokbot-nightlight.service runs /usr/local/bin/grokbot-nightlight, which
reads that file and runs gammastep (always on, or between two times of
day with a fade). grokbotd only writes the file and (re)starts or stops
the unit; nothing runs as root.
"""
import json
import os
import re
import shutil
import subprocess

from . import paths
from .backends import BackendError

UNIT = "grokbot-nightlight.service"
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
DEFAULTS = {"enabled": False, "temperature": 4000, "schedule": "always", "from": "20:00", "to": "07:00"}
TMIN, TMAX = 2500, 6000


def conf_path():
    return os.path.join(paths.config_home(), "grokbot", "nightlight.json")


def load():
    out = dict(DEFAULTS)
    try:
        with open(conf_path()) as f:
            d = json.load(f)
        if isinstance(d, dict):
            out.update({k: d[k] for k in DEFAULTS if k in d})
    except (OSError, ValueError):
        pass
    return out


def _systemctl(*args):
    if shutil.which("systemctl") is None:
        raise BackendError("systemctl is not available")
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BackendError("night light: %s" % e)
    return r.returncode, (r.stdout or r.stderr or "").strip()


def status(_params=None):
    c = load()
    available = shutil.which("gammastep") is not None
    running = False
    if available:
        try:
            running = _systemctl("is-active", UNIT)[0] == 0
        except BackendError:
            running = False
    c.update(available=available, running=running)
    return c


def set_nightlight(params):
    if shutil.which("gammastep") is None:
        raise BackendError("night light needs gammastep, which is not installed")
    c = load()
    for k in ("enabled", "temperature", "schedule", "from", "to"):
        if k in params:
            c[k] = params[k]
    c["temperature"] = int(c["temperature"])
    if not TMIN <= c["temperature"] <= TMAX:
        raise BackendError("temperature must be %d-%d K" % (TMIN, TMAX))
    if c["schedule"] not in ("always", "custom"):
        raise BackendError("schedule must be always or custom")
    for k in ("from", "to"):
        if not isinstance(c[k], str) or not TIME_RE.match(c[k]):
            raise BackendError("%s must be HH:MM" % k)
    if c["schedule"] == "custom" and c["from"] == c["to"]:
        raise BackendError("from and to must differ")
    p = conf_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({k: c[k] for k in DEFAULTS}, f, sort_keys=True)
    os.replace(tmp, p)
    rc, txt = _systemctl("restart" if c["enabled"] else "stop", UNIT)
    if rc != 0:
        raise BackendError("night light: %s" % (txt.splitlines()[-1] if txt else "could not start"))
    return status()


METHODS = {
    "display.nightlight.status": status,
    "display.nightlight.set": set_nightlight,
}
