"""audio.devices.list / audio.set_default: PipeWire output and input devices.

Devices (nodes) come from one `pw-dump` (JSON); the default sink and
source from its "default" metadata; per-device volume from `wpctl
get-volume ID`. Changes go through wpctl with the numeric node id, which
is checked against the current device list first, so nothing the caller
sends reaches a command line except a known integer.
"""
import json

from . import media, procs
from .backends import BackendError

KINDS = {"Audio/Sink": "output", "Audio/Source": "input"}


def _dump():
    out = procs.run(["pw-dump"], timeout=3)
    if out is None:
        return None
    try:
        objs = json.loads(out)
    except ValueError:
        return None
    return objs if isinstance(objs, list) else None


def _defaults(objs):
    d = {}
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Metadata":
            continue
        if ((o.get("props") or {}).get("metadata.name")) != "default":
            continue
        for m in o.get("metadata") or []:
            v = m.get("value")
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    v = {}
            if m.get("key") in ("default.audio.sink", "default.audio.source") and isinstance(v, dict):
                d[m["key"]] = v.get("name")
    return d


def devices(with_volume=True):
    objs = _dump()
    if objs is None:
        return None
    dfl = _defaults(objs)
    out = {"output": [], "input": []}
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        p = (o.get("info") or {}).get("props") or {}
        kind = KINDS.get(p.get("media.class"))
        if kind is None or not isinstance(o.get("id"), int):
            continue
        name = p.get("node.name") or ""
        dev = {"id": o["id"], "name": name,
               "description": p.get("node.description") or p.get("node.nick") or name,
               "bluetooth": p.get("device.api") == "bluez5",
               "default": name == dfl.get("default.audio.%s" % ("sink" if kind == "output" else "source"))}
        if with_volume:
            v = media._volume(str(o["id"])) or {}
            dev["volume_percent"] = v.get("volume_percent")
            dev["muted"] = v.get("muted")
        out[kind].append(dev)
    for k in out:
        out[k].sort(key=lambda d: (not d["default"], d["description"].lower()))
    return out


def audio_devices(_params):
    d = devices()
    if d is None:
        return {"available": False, "outputs": [], "inputs": []}
    return {"available": True, "outputs": d["output"], "inputs": d["input"]}


def find(dev_id, kind=None):
    d = devices(with_volume=False)
    if d is None:
        raise BackendError("PipeWire is not reachable (pw-dump)")
    for k in ("output", "input"):
        if kind and k != kind:
            continue
        for x in d[k]:
            if x["id"] == dev_id:
                return k, x
    raise BackendError("no such audio device: %s" % dev_id)


def audio_set_default(params):
    from .writes import _run
    _kind, _dev = find(int(params["id"]))
    _run(["wpctl", "set-default", str(int(params["id"]))])
    return audio_devices({})


METHODS = {
    "audio.devices.list": audio_devices,
    "audio.set_default": audio_set_default,
}
