"""bluetooth.*: adapters and devices through BlueZ on the system bus.

Reads use one D-Bus call (busctl GetManagedObjects, JSON), so the dock
can poll bluetooth.status cheaply. Changes are D-Bus method calls and
property sets with busctl. Discovery needs a client that stays on the bus
while it runs, so bluetooth.scan uses `bluetoothctl --timeout N scan on`.

Pairing runs with grokbotd's own BlueZ agent (btagent.py) registered for
that one Pair call: passkey confirmation and "type this code" go to the
consent prompt / a notification, and a PIN can be passed as "pin".
Without python3-gobject it falls back to a plain Pair ("just works" only).
Addresses are validated before they reach any command line.
"""
import json
import os
import re
import shutil
import subprocess

from .backends import BackendError

ADDR_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
BLUEZ = "org.bluez"


def _run(cmd, timeout=10):
    if shutil.which(cmd[0]) is None:
        raise BackendError("%s is not installed" % cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackendError("bluetooth: %s timed out" % cmd[0])
    except OSError as e:
        raise BackendError("bluetooth: %s failed: %s" % (cmd[0], e))
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise BackendError("bluetooth: %s" % _friendly(msg[-1] if msg else str(r.returncode)))
    return r.stdout


def _friendly(msg):
    for key, text in (("AuthenticationFailed", "pairing failed: the device needs a PIN or passkey, or refused"),
                      ("AuthenticationCanceled", "pairing was cancelled on the device"),
                      ("ConnectionAttemptFailed", "the device did not answer (is it on and in range?)"),
                      ("org.bluez.Error.Blocked", "Bluetooth is blocked (airplane mode / rfkill)"),
                      ("org.bluez.Error.NotReady", "the adapter is off"),
                      ("AlreadyExists", "the device is already paired"),
                      ("DoesNotExist", "unknown device"),
                      ("ServiceUnknown", "the Bluetooth service (bluetoothd) is not running")):
        if key in msg:
            return text
    return msg[:200]


def _val(v):
    return v.get("data") if isinstance(v, dict) and "type" in v else v


def objects():
    """{path: {iface: {prop: value}}} from BlueZ, or None if BlueZ is not on the bus."""
    try:
        out = _run(["busctl", "--system", "--json=short", "call", BLUEZ, "/",
                    "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"], timeout=3)
    except BackendError:
        return None
    try:
        data = json.loads(out)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return {p: {i: {k: _val(v) for k, v in props.items()} for i, props in ifs.items()}
            for p, ifs in data.items()}


def _device(path, ifs):
    d = ifs.get("org.bluez.Device1", {})
    bat = ifs.get("org.bluez.Battery1", {}).get("Percentage")
    return {
        "address": d.get("Address"),
        "name": d.get("Alias") or d.get("Name") or d.get("Address"),
        "icon": d.get("Icon") or "bluetooth",
        "paired": bool(d.get("Paired")),
        "trusted": bool(d.get("Trusted")),
        "connected": bool(d.get("Connected")),
        "blocked": bool(d.get("Blocked")),
        "rssi": d.get("RSSI"),
        "battery_percent": bat,
        "adapter": d.get("Adapter"),
        "path": path,
    }


def _state():
    objs = objects()
    if objs is None:
        return None, [], []
    adapters, devices = [], []
    for path, ifs in sorted(objs.items()):
        a = ifs.get("org.bluez.Adapter1")
        if a is not None:
            adapters.append({"path": path, "name": path.rsplit("/", 1)[-1], "address": a.get("Address"),
                             "alias": a.get("Alias"), "powered": bool(a.get("Powered")),
                             "discovering": bool(a.get("Discovering")),
                             "discoverable": bool(a.get("Discoverable"))})
        if "org.bluez.Device1" in ifs:
            devices.append(_device(path, ifs))
    return objs, adapters, devices


def bluetooth_status(_params):
    objs, adapters, devices = _state()
    if objs is None:
        return {"available": False, "service": False, "powered": False, "adapters": [], "devices": []}
    known = [d for d in devices if d["paired"] or d["connected"] or d["trusted"]]
    return {"available": bool(adapters), "service": True,
            "powered": any(a["powered"] for a in adapters),
            "adapters": adapters, "devices": known,
            "connected": [d["name"] for d in known if d["connected"]]}


def _adapter():
    objs, adapters, _ = _state()
    if objs is None:
        raise BackendError("bluetooth: the Bluetooth service (bluetoothd) is not running")
    if not adapters:
        raise BackendError("bluetooth: no Bluetooth adapter found")
    return adapters[0]


def _dev_path(address):
    if not isinstance(address, str) or not ADDR_RE.match(address.upper()):
        raise BackendError("bad Bluetooth address")
    _, _, devices = _state()
    for d in devices:
        if (d["address"] or "").upper() == address.upper():
            return d
    raise BackendError("bluetooth: unknown device %s (scan first)" % address)


def _set_prop(path, iface, prop, value):
    _run(["busctl", "--system", "set-property", BLUEZ, path, iface, prop, "b", "true" if value else "false"])


def _dev_call(dev, method, timeout=40):
    _run(["busctl", "--system", "--timeout=%d" % timeout, "call", BLUEZ, dev["path"],
          "org.bluez.Device1", method], timeout=timeout + 5)


def bluetooth_set_power(params):
    a = _adapter()
    on = bool(params["powered"])
    if on:
        # Soft-blocked radios (airplane mode) refuse Powered=true; the
        # session user may unblock through /dev/rfkill (logind uaccess).
        if shutil.which("rfkill"):
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=5)
    _set_prop(a["path"], "org.bluez.Adapter1", "Powered", on)
    return bluetooth_status({})


def bluetooth_scan(params):
    a = _adapter()
    if not a["powered"]:
        raise BackendError("bluetooth: the adapter is off")
    secs = int(params.get("seconds", 8))
    _run(["bluetoothctl", "--timeout", str(secs), "scan", "on"], timeout=secs + 10)
    _, _, devices = _state()
    found = [d for d in devices if not d["paired"]]
    found.sort(key=lambda d: -(d["rssi"] if isinstance(d["rssi"], int) else -999))
    return {"devices": found, "seconds": secs}


def _agent_available():
    if os.environ.get("GROKBOT_BT_AGENT", "1") == "0":
        return False
    try:
        import gi  # noqa: F401
        return True
    except ImportError:
        return False


def _ask(kind, ko, en, code):
    from . import consent
    ans, _ = consent.prompt("grokbotd", "Bluetooth", "bluetooth", "bluetooth.pair", [ko, en],
                            {"passkey": code} if code else {}, False, allow_session=False, allow_once=True)
    return ans == "once"


def _show(kind, ko, en, code):
    try:
        subprocess.run(["notify-send", "-a", "Bluetooth", "-u", "critical", "-t", "60000",
                        "Bluetooth: %s" % code, "%s\n%s" % (ko, en)], timeout=5, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


def bluetooth_pair(params):
    from . import btagent
    d = _dev_path(params["address"])
    pin = btagent.check_pin(params.get("pin"))
    if not d["paired"]:
        if _agent_available():
            btagent.pair(d["path"], btagent.Handler(d["path"], d.get("name"), pin, _ask, _show))
        elif pin:
            raise BackendError("bluetooth: PIN pairing needs python3-gobject")
        else:
            _dev_call(d, "Pair")
    _set_prop(d["path"], "org.bluez.Device1", "Trusted", True)
    if params.get("connect", True):
        _dev_call(d, "Connect")
    return _dev_path(params["address"])


def bluetooth_connect(params):
    d = _dev_path(params["address"])
    _dev_call(d, "Connect")
    return _dev_path(params["address"])


def bluetooth_disconnect(params):
    d = _dev_path(params["address"])
    _dev_call(d, "Disconnect", timeout=15)
    return _dev_path(params["address"])


def bluetooth_trust(params):
    d = _dev_path(params["address"])
    _set_prop(d["path"], "org.bluez.Device1", "Trusted", bool(params["trusted"]))
    return _dev_path(params["address"])


def bluetooth_remove(params):
    d = _dev_path(params["address"])
    _run(["busctl", "--system", "call", BLUEZ, d["adapter"] or d["path"].rsplit("/", 1)[0],
          "org.bluez.Adapter1", "RemoveDevice", "o", d["path"]])
    return {"removed": d["address"]}


METHODS = {
    "bluetooth.status": bluetooth_status,
    "bluetooth.set_power": bluetooth_set_power,
    "bluetooth.scan": bluetooth_scan,
    "bluetooth.pair": bluetooth_pair,
    "bluetooth.connect": bluetooth_connect,
    "bluetooth.disconnect": bluetooth_disconnect,
    "bluetooth.trust": bluetooth_trust,
    "bluetooth.remove": bluetooth_remove,
}
