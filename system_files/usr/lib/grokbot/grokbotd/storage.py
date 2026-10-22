"""storage.*: removable drives (USB sticks, SD cards, external disks)
through UDisks2 on the system bus.

storage.list reads everything in one GetManagedObjects call (busctl
JSON) and keeps only filesystems on removable or USB drives, never the
system disk. mount / unmount / eject are UDisks2 method calls; polkit
lets the active local session do them for removable media without a
password. Volumes are named by their block device (sdb1), validated and
looked up in the current list before any call.
"""
import json
import re
import shutil
import subprocess

from .backends import BackendError

UD = "org.freedesktop.UDisks2"
ROOT = "/org/freedesktop/UDisks2"
ID_RE = re.compile(r"^[a-z][a-z0-9]{1,31}$")


def _run(cmd, timeout=30):
    if shutil.which(cmd[0]) is None:
        raise BackendError("%s is not installed" % cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackendError("storage: timed out")
    except OSError as e:
        raise BackendError("storage: %s" % e)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise BackendError("storage: %s" % _friendly(msg[-1] if msg else str(r.returncode)))
    return r.stdout


def _friendly(msg):
    for key, text in (("DeviceBusy", "the drive is in use: close the files and apps using it, then try again"),
                      ("NotAuthorized", "not allowed by the system policy"),
                      ("AlreadyMounted", "already open"),
                      ("NotMounted", "not open"),
                      ("ServiceUnknown", "the storage service (udisks2) is not running")):
        if key in msg:
            return text
    return msg[:200]


def _val(v):
    return v.get("data") if isinstance(v, dict) and "type" in v else v


def _bytes(v):
    """D-Bus 'ay' (NUL-terminated) to str."""
    if isinstance(v, list):
        return bytes(b for b in v if isinstance(b, int) and 0 < b < 256).decode("utf-8", "replace")
    return v or ""


def objects():
    try:
        out = _run(["busctl", "--system", "--json=short", "call", UD, ROOT,
                    "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"], timeout=5)
        data = json.loads(out)["data"][0]
    except (BackendError, ValueError, KeyError, IndexError, TypeError):
        return None
    return {p: {i: {k: _val(v) for k, v in props.items()} for i, props in ifs.items()}
            for p, ifs in data.items()}


def volumes(objs=None):
    objs = objects() if objs is None else objs
    if objs is None:
        return None
    out = []
    for path, ifs in sorted(objs.items()):
        blk = ifs.get("org.freedesktop.UDisks2.Block")
        if blk is None or "org.freedesktop.UDisks2.Filesystem" not in ifs:
            continue
        if blk.get("HintIgnore") or blk.get("IdUsage") != "filesystem":
            continue
        drive = objs.get(blk.get("Drive") or "", {}).get("org.freedesktop.UDisks2.Drive", {})
        removable = bool(drive.get("Removable") or drive.get("MediaRemovable") or drive.get("ConnectionBus") == "usb")
        if not removable:
            continue
        mps = [_bytes(m) for m in ifs["org.freedesktop.UDisks2.Filesystem"].get("MountPoints") or []]
        dev = _bytes(blk.get("PreferredDevice") or blk.get("Device"))
        name = path.rsplit("/", 1)[-1]
        label = blk.get("IdLabel") or ""
        model = " ".join(x for x in (drive.get("Vendor"), drive.get("Model")) if x).strip()
        out.append({"id": name, "device": dev, "label": label,
                    "name": label or model or name, "drive": model,
                    "fs": blk.get("IdType") or "", "size": blk.get("Size") or 0,
                    "mounted": bool(mps), "mount_points": mps,
                    "read_only": bool(blk.get("ReadOnly")),
                    "ejectable": bool(drive.get("Ejectable")),
                    "path": path, "drive_path": blk.get("Drive") or None})
    return out


def storage_list(_params):
    v = volumes()
    if v is None:
        return {"available": False, "volumes": []}
    return {"available": True, "volumes": v}


def _find(vid):
    if not isinstance(vid, str) or not ID_RE.match(vid):
        raise BackendError("bad volume id")
    v = volumes()
    if v is None:
        raise BackendError("storage: the storage service (udisks2) is not running")
    for x in v:
        if x["id"] == vid:
            return x
    raise BackendError("storage: no such removable volume: %s" % vid)


def storage_mount(params):
    v = _find(params["id"])
    if not v["mounted"]:
        _run(["busctl", "--system", "call", UD, v["path"], "org.freedesktop.UDisks2.Filesystem",
              "Mount", "a{sv}", "0"])
    return _find(params["id"])


def storage_unmount(params):
    v = _find(params["id"])
    if v["mounted"]:
        _run(["busctl", "--system", "call", UD, v["path"], "org.freedesktop.UDisks2.Filesystem",
              "Unmount", "a{sv}", "0"])
    out = {"id": v["id"], "mounted": False, "ejected": False}
    if params.get("eject") and v["drive_path"]:
        # Unmount every other open volume on the same drive first.
        for o in volumes() or []:
            if o["drive_path"] == v["drive_path"] and o["mounted"]:
                _run(["busctl", "--system", "call", UD, o["path"], "org.freedesktop.UDisks2.Filesystem",
                      "Unmount", "a{sv}", "0"])
        method = "Eject" if v["ejectable"] else "PowerOff"
        _run(["busctl", "--system", "call", UD, v["drive_path"], "org.freedesktop.UDisks2.Drive",
              method, "a{sv}", "0"])
        out["ejected"] = True
    return out


METHODS = {
    "storage.list": storage_list,
    "storage.mount": storage_mount,
    "storage.unmount": storage_unmount,
}
