"""storage.*: removable drives (USB sticks, SD cards, external disks)
through UDisks2 on the system bus.

storage.list reads everything in one GetManagedObjects call (busctl
JSON) and keeps only filesystems on removable or USB drives, never the
system disk. mount / unmount / eject are UDisks2 method calls; polkit
lets the active local session do them for removable media without a
password. Volumes are named by their UDisks2 block object (sdb1, dm_2d0),
validated and looked up in the current list before any call.

Encrypted (LUKS) drives: the locked container is listed with
encrypted=true, locked=true. storage.unlock asks for the passphrase in
the secure prompt (grokbot-consent, secret mode) and passes it to
UDisks2 Encrypted.Unlock over D-Bus in this process: never on a command
line, in params, the audit log or a file. The unlocked filesystem is
listed as its own volume with backing=<container id>; storage.lock (and
eject) close it again. exFAT and NTFS mount like any other file system
(exfat / ntfs3 kernel drivers, /etc/udisks2/mount_options.conf).
"""
import json
import re
import shutil
import subprocess

from .backends import BackendError

UD = "org.freedesktop.UDisks2"
ROOT = "/org/freedesktop/UDisks2"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
ENC = "org.freedesktop.UDisks2.Encrypted"
FS = "org.freedesktop.UDisks2.Filesystem"
MAX_PASSPHRASE = 512


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
                      ("ServiceUnknown", "the storage service (udisks2) is not running"),
                      ("wrong passphrase", "wrong passphrase"), ("Failed to activate", "wrong passphrase"),
                      ("unknown filesystem type 'ntfs", "NTFS is not supported by this kernel"),
                      ("unknown filesystem type", "this file system type is not supported")):
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
        if blk is None or blk.get("HintIgnore"):
            continue
        encrypted = ENC in ifs and blk.get("IdUsage") == "crypto"
        if not encrypted and (FS not in ifs or blk.get("IdUsage") != "filesystem"):
            continue
        backing = blk.get("CryptoBackingDevice") or "/"
        backing = backing if backing != "/" and backing in objs else None
        drive_path = blk.get("Drive") or "/"
        if drive_path == "/" and backing:
            drive_path = objs[backing].get("org.freedesktop.UDisks2.Block", {}).get("Drive") or "/"
        drive = objs.get(drive_path, {}).get("org.freedesktop.UDisks2.Drive", {})
        removable = bool(drive.get("Removable") or drive.get("MediaRemovable") or drive.get("ConnectionBus") == "usb")
        if not removable:
            continue
        if encrypted:
            clear = ifs[ENC].get("CleartextDevice") or "/"
            if clear != "/" and clear in objs:
                continue  # unlocked: the cleartext volume below stands for it
            mps = []
        else:
            mps = [_bytes(m) for m in ifs[FS].get("MountPoints") or []]
        dev = _bytes(blk.get("PreferredDevice") or blk.get("Device"))
        name = path.rsplit("/", 1)[-1]
        label = blk.get("IdLabel") or ""
        if not label and backing:
            label = objs[backing].get("org.freedesktop.UDisks2.Block", {}).get("IdLabel") or ""
        model = " ".join(x for x in (drive.get("Vendor"), drive.get("Model")) if x).strip()
        v = {"id": name, "device": dev, "label": label,
             "name": label or model or name, "drive": model,
             "fs": blk.get("IdType") or "", "size": blk.get("Size") or 0,
             "mounted": bool(mps), "mount_points": mps,
             "read_only": bool(blk.get("ReadOnly")),
             "ejectable": bool(drive.get("Ejectable")),
             "encrypted": bool(encrypted or backing), "locked": bool(encrypted),
             "backing": backing.rsplit("/", 1)[-1] if backing else None,
             "path": path, "drive_path": drive_path if drive_path != "/" else None}
        if backing:
            v["backing_path"] = backing
        out.append(v)
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
    if v["locked"]:
        raise BackendError("storage: the drive is encrypted; unlock it first (storage.unlock)")
    if not v["mounted"]:
        _run(["busctl", "--system", "call", UD, v["path"], "org.freedesktop.UDisks2.Filesystem",
              "Mount", "a{sv}", "0"])
    return _find(params["id"])


def _call_unmount(o):
    _run(["busctl", "--system", "call", UD, o["path"], FS, "Unmount", "a{sv}", "0"])


def _call_lock(backing_path):
    _run(["busctl", "--system", "call", UD, backing_path, ENC, "Lock", "a{sv}", "0"])


def storage_unmount(params):
    v = _find(params["id"])
    if v["mounted"]:
        _call_unmount(v)
    out = {"id": v["id"], "mounted": False, "ejected": False, "locked": v["locked"]}
    if params.get("eject") and v["drive_path"]:
        # Close every other open volume on the same drive first, and lock
        # unlocked encrypted ones so no cleartext mapping stays behind.
        for o in volumes() or []:
            if o["drive_path"] != v["drive_path"]:
                continue
            if o["mounted"]:
                _call_unmount(o)
            if o.get("backing_path"):
                _call_lock(o["backing_path"])
        method = "Eject" if v["ejectable"] else "PowerOff"
        _run(["busctl", "--system", "call", UD, v["drive_path"], "org.freedesktop.UDisks2.Drive",
              method, "a{sv}", "0"])
        out.update(ejected=True, locked=bool(v["encrypted"]))
    return out


def _unlock_dbus(path, passphrase):
    """Encrypted.Unlock over the system bus from this process (Gio), so the
    passphrase never appears on a command line. Returns the cleartext path."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        raise BackendError("storage: python3-gobject is not installed")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        r = bus.call_sync(UD, path, ENC, "Unlock",
                          GLib.Variant("(sa{sv})", (passphrase, {})), GLib.VariantType("(o)"),
                          Gio.DBusCallFlags.NONE, 60000, None)
        return r.unpack()[0]
    except GLib.Error as e:
        msg = e.message or ""
        # never echo anything that could contain the passphrase
        raise BackendError("storage: %s" % _friendly(msg.replace(passphrase, "***") if passphrase else msg))


def _secret_prompt(ctx, v):
    from . import consent
    name = v["label"] or v["drive"] or v["id"]
    return consent.secret_prompt(
        ctx["principal"], ctx.get("client"), "storage", "storage.unlock",
        ["암호화된 드라이브 잠금 해제: %s" % name, "Unlock encrypted drive: %s" % name],
        {"id": v["id"], "drive": v["drive"]},
        ["암호를 입력하세요. 암호는 저장하거나 기록하지 않습니다.",
         "Enter the passphrase. It is never stored or logged."])


def storage_unlock(params, ctx):
    from .webapps import Denied
    v = _find(params["id"])
    if not v["locked"]:
        raise BackendError("storage: not a locked encrypted drive")
    ans, detail, secret = _secret_prompt(ctx, v)
    if ans != "once" or not secret:
        raise Denied(detail)
    if len(secret) > MAX_PASSPHRASE:
        raise BackendError("storage: passphrase too long")
    try:
        clear = _unlock_dbus(v["path"], secret)
    finally:
        secret = None  # noqa: F841 (drop the reference as early as we can)
    cid = clear.rsplit("/", 1)[-1]
    if params.get("mount", True):
        try:
            return storage_mount({"id": cid})
        except BackendError:
            pass  # e.g. no file system inside; still unlocked
    for x in volumes() or []:
        if x["id"] == cid:
            return x
    return {"id": cid, "locked": False, "encrypted": True, "backing": v["id"], "mounted": False}


def storage_lock(params):
    v = _find(params["id"])
    if v["locked"]:
        return {"id": v["id"], "locked": True}
    if not v.get("backing_path"):
        raise BackendError("storage: not an unlocked encrypted drive")
    if v["mounted"]:
        _call_unmount(v)
    _call_lock(v["backing_path"])
    return {"id": v["backing"], "locked": True}


METHODS = {
    "storage.list": storage_list,
    "storage.mount": storage_mount,
    "storage.unmount": storage_unmount,
    "storage.lock": storage_lock,
}
CTX_METHODS = {
    "storage.unlock": storage_unlock,
}
