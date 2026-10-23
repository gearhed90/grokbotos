"""network.connections.* / network.vpn.* : wired and VPN through NetworkManager (nmcli).

Only ethernet, vpn (OpenVPN, ...) and wireguard profiles are listed or
touched here (Wi-Fi has network.wifi.*). Connections are addressed by
NetworkManager UUID, checked against the list before any nmcli call.
VPN profiles are imported from a .conf (WireGuard) or .ovpn (OpenVPN)
file in the home folder, resolved with the files scope rules (no hidden
paths, no symlinks out of ~). Secrets are never returned: list output
holds names, types, devices, state and addresses only.
"""
import ipaddress
import os
import re

from . import files
from .backends import BackendError
from .writes import _nm_split, _run

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
KINDS = {"802-3-ethernet": "wired", "ethernet": "wired", "vpn": "vpn", "wireguard": "vpn"}
IMPORT_TYPES = {".conf": "wireguard", ".ovpn": "openvpn"}


def _connections():
    out = _run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE,ACTIVE,STATE", "connection", "show"], what="nmcli")
    res = []
    for line in out.splitlines():
        f = _nm_split(line)
        if len(f) < 6 or f[2] not in KINDS:
            continue
        res.append({"name": f[0], "uuid": f[1], "type": f[2], "kind": KINDS[f[2]],
                    "device": f[3] or None, "active": f[4] == "yes",
                    "state": f[5] or ("activated" if f[4] == "yes" else "inactive")})
    return res


def _wired_devices():
    out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], what="nmcli")
    res = []
    for line in out.splitlines():
        f = _nm_split(line)
        if len(f) >= 4 and f[1] == "ethernet":
            res.append({"device": f[0], "state": f[2], "connection": f[3] or None,
                        "cable": f[2] not in ("unavailable",)})
    return res


def _ipv4(uuid):
    out = _run(["nmcli", "-t", "-f", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,IP4.ADDRESS",
                "connection", "show", uuid], what="nmcli")
    r = {"method": None, "addresses": [], "gateway": None, "dns": [], "current": []}
    for line in out.splitlines():
        k, _, v = line.partition(":")
        v = v.replace("\\:", ":")
        if k == "ipv4.method":
            r["method"] = v or None
        elif k == "ipv4.addresses":
            r["addresses"] = [a.strip() for a in v.split(",") if a.strip()]
        elif k == "ipv4.gateway":
            r["gateway"] = v if v and v != "--" else None
        elif k == "ipv4.dns":
            r["dns"] = [a.strip() for a in v.split(",") if a.strip()]
        elif k.startswith("IP4.ADDRESS"):
            r["current"].append(v)
    return r


def network_connections_list(params):
    conns = _connections()
    for c in conns:
        if c["kind"] == "wired":
            try:
                c["ipv4"] = _ipv4(c["uuid"])
            except BackendError:
                c["ipv4"] = None
    return {"connections": conns, "wired_devices": _wired_devices(),
            "vpn_active": [c["name"] for c in conns if c["kind"] == "vpn" and c["active"]]}


def _find(uuid, kinds=("wired", "vpn")):
    if not isinstance(uuid, str) or not UUID_RE.match(uuid):
        raise BackendError("bad connection uuid")
    for c in _connections():
        if c["uuid"].lower() == uuid.lower() and c["kind"] in kinds:
            return c
    raise BackendError("no such wired or VPN connection")


def network_connection_up(params):
    c = _find(params["uuid"])
    _run(["nmcli", "--wait", "30", "connection", "up", "uuid", c["uuid"]], timeout=40, what="connect")
    return _find(c["uuid"])


def network_connection_down(params):
    c = _find(params["uuid"])
    if c["active"]:
        _run(["nmcli", "connection", "down", "uuid", c["uuid"]], timeout=20, what="disconnect")
    return _find(c["uuid"])


def network_wired_configure(params):
    c = _find(params["uuid"], kinds=("wired",))
    method = params["ipv4"]
    args = ["nmcli", "connection", "modify", "uuid", c["uuid"]]
    if method == "auto":
        args += ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
    else:
        try:
            iface = ipaddress.IPv4Interface(params.get("address", ""))
        except ValueError:
            raise BackendError("address must look like 192.168.1.20/24")
        if iface.network.prefixlen in (0, 32) or iface.ip == iface.network.network_address:
            raise BackendError("address must be a host address with a prefix such as /24")
        args += ["ipv4.method", "manual", "ipv4.addresses", str(iface)]
        gw = params.get("gateway")
        if gw:
            try:
                g = ipaddress.IPv4Address(gw)
            except ValueError:
                raise BackendError("bad gateway")
            if g not in iface.network:
                raise BackendError("the gateway must be in the same network as the address")
            args += ["ipv4.gateway", str(g)]
        else:
            args += ["ipv4.gateway", ""]
        dns = []
        for d in params.get("dns", []):
            try:
                dns.append(str(ipaddress.ip_address(d)))
            except ValueError:
                raise BackendError("bad DNS server %r" % d)
        args += ["ipv4.dns", ",".join(dns)]
    _run(args, what="nmcli")
    if c["active"]:
        _run(["nmcli", "--wait", "30", "connection", "up", "uuid", c["uuid"]], timeout=40, what="reconnect")
    r = _find(c["uuid"], kinds=("wired",))
    r["ipv4"] = _ipv4(c["uuid"])
    return r


def network_vpn_import(params):
    path = files.resolve(params["path"])
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORT_TYPES or not os.path.isfile(path):
        raise BackendError("choose a WireGuard .conf or OpenVPN .ovpn file")
    if os.path.getsize(path) > 256 * 1024:
        raise BackendError("file is too large for a VPN profile")
    before = {c["uuid"] for c in _connections()}
    _run(["nmcli", "connection", "import", "type", IMPORT_TYPES[ext], "file", path], timeout=20,
         what="VPN import")
    new = [c for c in _connections() if c["uuid"] not in before and c["kind"] == "vpn"]
    return {"imported": new}


def network_vpn_delete(params):
    c = _find(params["uuid"], kinds=("vpn",))
    _run(["nmcli", "connection", "delete", "uuid", c["uuid"]], timeout=20, what="delete")
    return {"deleted": c["uuid"], "name": c["name"]}


METHODS = {
    "network.connections.list": network_connections_list,
    "network.connection.up": network_connection_up,
    "network.connection.down": network_connection_down,
    "network.wired.configure": network_wired_configure,
    "network.vpn.import": network_vpn_import,
    "network.vpn.delete": network_vpn_delete,
}
