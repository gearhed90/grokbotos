"""power.profile.*: power mode (power-saver / balanced / performance)
through the power-profiles D-Bus API (tuned-ppd on Fedora; the same API
as power-profiles-daemon). Polkit lets the active session switch.
"""
import json
import shutil
import subprocess

from .backends import BackendError

BUS = "org.freedesktop.UPower.PowerProfiles"
PATH = "/org/freedesktop/UPower/PowerProfiles"
PROFILES = ("power-saver", "balanced", "performance")


def _run(cmd, timeout=5):
    if shutil.which(cmd[0]) is None:
        raise BackendError("%s is not installed" % cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise BackendError("power mode: %s" % type(e).__name__)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        m = msg[-1] if msg else str(r.returncode)
        if "ServiceUnknown" in m or "not activatable" in m or "was not provided" in m:
            m = "the power mode service (tuned-ppd) is not running"
        raise BackendError("power mode: %s" % m[:200])
    return r.stdout


def _props():
    out = _run(["busctl", "--system", "--json=short", "get-property", BUS, PATH, BUS,
                "ActiveProfile", "Profiles", "PerformanceDegraded"])
    vals = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            vals.append(json.loads(line).get("data"))
    if len(vals) < 2:
        raise BackendError("power mode: unexpected answer")
    profiles = []
    for p in vals[1] or []:
        name = p.get("Profile", {}).get("data") if isinstance(p.get("Profile"), dict) else p.get("Profile")
        if name in PROFILES:
            profiles.append(name)
    return {"active": vals[0], "profiles": [p for p in PROFILES if p in profiles],
            "degraded": (vals[2] if len(vals) > 2 else "") or ""}


def profile_status(_params):
    try:
        p = _props()
    except (BackendError, ValueError, AttributeError):
        return {"available": False, "active": None, "profiles": [], "degraded": ""}
    p["available"] = True
    return p


def profile_set(params):
    want = params["profile"]
    if want not in PROFILES:
        raise BackendError("unknown power mode")
    cur = _props()
    if want not in cur["profiles"]:
        raise BackendError("power mode %s is not offered on this computer" % want)
    _run(["busctl", "--system", "set-property", BUS, PATH, BUS, "ActiveProfile", "s", want])
    return profile_status({})


METHODS = {
    "power.profile.status": profile_status,
    "power.profile.set": profile_set,
}
