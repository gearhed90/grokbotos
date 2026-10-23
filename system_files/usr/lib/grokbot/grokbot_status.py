"""Status items for the dock: camera/microphone in use, Wi-Fi, volume,
battery, clock.

Data comes from grokbotd (privacy.status, power.status, network.status, audio.status)
over the user's unix socket, so the dock is just another OS API client.
No GTK here, so it can be unit-tested.
"""
import json
import os
import socket
import time

EDGES = ("top", "bottom", "left", "right")


def socket_path():
    return os.environ.get("GROKBOT_API_SOCK") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "grokbot", "api.sock")


def rpc(method, timeout=1.0):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(timeout)
        s.connect(socket_path())
        f = s.makefile("rwb")
        f.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}) + "\n").encode())
        f.flush()
        r = json.loads(f.readline() or b"{}")
        s.close()
        return r.get("result")
    except (OSError, ValueError):
        return None


def status_edge(conf):
    """Which edge shows the status area, or None."""
    want = conf.get("status", "auto")
    if want == "off":
        return None
    if want in EDGES:
        return want if conf.get(want, "off") != "off" else None
    for e in ("bottom", "top", "right", "left"):
        if conf.get(e, "off") != "off":
            return e
    return None


def _battery(power):
    if not power or not power.get("batteries"):
        return None
    b = power["batteries"][0]
    cap = b.get("capacity_percent")
    status = (b.get("status") or "").lower()
    on_ac = bool(power.get("on_ac"))
    # Charging and Discharging come from the kernel status string.
    # Anything else while on AC (Unknown, empty, None, Not charging, Full)
    # still means the adapter is connected. Some ACPI and charge-threshold
    # laptops never leave Unknown.
    charging = status == "charging"
    discharging = status == "discharging"
    plugged = on_ac and not charging and not discharging
    if cap is None:
        level, pct = None, "?"
    else:
        level = min(100, max(0, int(round(cap / 10.0)) * 10))
        pct = "%s%%" % cap
    if charging:
        icon = "battery-missing-symbolic" if level is None else "battery-level-%d-charging-symbolic" % level
        text = "충전 중"
        tip = "충전 중 / Charging %s" % pct
    elif plugged:
        if status == "full":
            # Adwaita status icon: full battery plus a charged mark.
            # Not charging keeps the plug (ac-adapter-symbolic) so an
            # icon-only dock can tell the two apart.
            icon = "battery-level-100-charged-symbolic"
            text, tip = "전원 연결됨 (가득 참)", "전원 연결됨 (가득 참) / Plugged in (full)"
        else:
            icon = "ac-adapter-symbolic"
            text, tip = "전원 연결됨", "전원 연결됨 / Plugged in %s" % pct
    else:
        icon = "battery-missing-symbolic" if level is None else "battery-level-%d-symbolic" % level
        text = pct
        tip = "배터리 / Battery %s" % pct
    return {"id": "battery", "icon": icon, "text": text, "tooltip": tip}


def _network(net):
    if net is None:
        return None
    ifs = [i for i in net.get("interfaces", []) if i.get("name") != "lo"]
    route = net.get("default_route") or {}
    up = [i for i in ifs if i.get("state") == "up" and i.get("addresses")]
    dev = next((i for i in up if i.get("name") == route.get("interface")), up[0] if up else None)
    if not net.get("online") or dev is None:
        return {"id": "network", "icon": "network-offline-symbolic", "text": "오프라인",
                "tooltip": "연결 안 됨 / Offline. 클릭: Wi-Fi 설정 / Click: Wi-Fi settings"}
    if dev.get("wireless"):
        return {"id": "network", "icon": "network-wireless-signal-good-symbolic", "text": "Wi-Fi",
                "tooltip": "Wi-Fi: %s" % dev["name"]}
    return {"id": "network", "icon": "network-wired-symbolic", "text": "유선", "page": "network",
            "tooltip": "유선 / Wired: %s. 클릭: 유선·VPN 설정 / Click: Wired and VPN settings" % dev["name"]}


def _vpn(conns):
    """Shown only while a VPN is up."""
    if not conns or not conns.get("vpn_active"):
        return None
    names = ", ".join(conns["vpn_active"])
    return {"id": "vpn", "icon": "network-vpn-symbolic", "text": "VPN",
            "tooltip": "VPN 연결됨 / VPN on: %s. 클릭: 유선·VPN 설정 / Click: Wired and VPN settings" % names}


def _volume(audio):
    if not audio or not audio.get("available") or not audio.get("output"):
        return None
    o = audio["output"]
    v = o.get("volume_percent") or 0
    if o.get("muted") or v == 0:
        icon = "audio-volume-muted-symbolic"
    elif v < 34:
        icon = "audio-volume-low-symbolic"
    elif v < 67:
        icon = "audio-volume-medium-symbolic"
    else:
        icon = "audio-volume-high-symbolic"
    text = "음소거" if o.get("muted") else "%d%%" % v
    return {"id": "volume", "icon": icon, "text": text,
            "tooltip": "볼륨 / Volume %s. 클릭: 음소거, 스크롤: 조절 / Click: mute, scroll: adjust" % text}


def _bluetooth(bt):
    """Shown only when there is an adapter: off, on, or connected (names)."""
    if not bt or not bt.get("available"):
        return None
    names = bt.get("connected") or []
    if not bt.get("powered"):
        return {"id": "bluetooth", "icon": "bluetooth-disabled-symbolic", "text": "꺼짐",
                "tooltip": "블루투스 꺼짐 / Bluetooth off. 클릭: 블루투스 설정 / Click: Bluetooth settings"}
    if names:
        return {"id": "bluetooth", "icon": "bluetooth-active-symbolic", "text": names[0][:16],
                "tooltip": "블루투스 연결됨 / Bluetooth connected: %s. 클릭: 블루투스 설정 / Click: Bluetooth settings"
                           % ", ".join(names)}
    return {"id": "bluetooth", "icon": "bluetooth-symbolic", "text": "켜짐",
            "tooltip": "블루투스 켜짐, 연결된 기기 없음 / Bluetooth on, nothing connected. "
                       "클릭: 블루투스 설정 / Click: Bluetooth settings"}
def _mic(audio):
    """Microphone muted: a reminder at the end of the dock (click: unmute)."""
    if not audio or not audio.get("available") or not audio.get("input"):
        return None
    if not audio["input"].get("muted"):
        return None
    return {"id": "mic-muted", "icon": "microphone-sensitivity-muted-symbolic", "text": "마이크 꺼짐",
            "tooltip": "마이크 음소거됨 / Microphone muted. 클릭: 음소거 해제 / Click: unmute"}
def _storage(st):
    """Removable drives plugged in: one item; click opens Settings > Storage."""
    vols = (st or {}).get("volumes") or []
    if not vols:
        return None
    names = ", ".join(v.get("name") or v.get("id") or "?" for v in vols)
    opened = [v for v in vols if v.get("mounted")]
    return {"id": "storage", "icon": "media-removable-symbolic", "text": "USB",
            "tooltip": "외장 저장장치 / Removable drives: %s (%d 열림 / open). 클릭: 꺼내기 / Click: safely remove"
                       % (names, len(opened))}
def _printing(pr):
    """Print jobs waiting: one item while any job is queued, highlighted
    when a printer with jobs is stopped. Click: Settings > Printers."""
    jobs = (pr or {}).get("jobs") or []
    if not jobs:
        return None
    stopped = {p["name"] for p in pr.get("printers", []) if p.get("state") == "stopped"}
    stuck = sorted({j["printer"] for j in jobs if j.get("printer") in stopped})
    it = {"id": "printing", "icon": "printer-symbolic", "text": "인쇄 %d" % len(jobs),
          "tooltip": "인쇄 작업 %d개 / %d print job(s). 클릭: 프린터 / Click: Printers" % (len(jobs), len(jobs))}
    if stuck:
        it["alert"] = True
        it["tooltip"] = "프린터 멈춤 / Printer stopped: %s. " % ", ".join(stuck) + it["tooltip"]
    return it


def _power_mode(pm):
    """Shown only when not balanced (the default), so a forgotten power
    saver or performance mode is visible. Click: Settings > Power."""
    if not pm or not pm.get("available") or pm.get("active") in (None, "balanced"):
        return None
    if pm["active"] == "power-saver":
        return {"id": "power-mode", "icon": "power-profile-power-saver-symbolic", "text": "절전",
                "tooltip": "전원 모드: 절전 / Power mode: power saver. 클릭: 전원 설정 / Click: Power settings"}
    tip = "전원 모드: 성능 / Power mode: performance"
    if pm.get("degraded"):
        tip += " (제한됨 / limited: %s)" % pm["degraded"]
    return {"id": "power-mode", "icon": "power-profile-performance-symbolic", "text": "성능",
            "tooltip": tip + ". 클릭: 전원 설정 / Click: Power settings"}


def _who(sess):
    p = sess.get("principal") or "?"
    name = p[7:] if p.startswith("origin:") else ("이 컴퓨터 / local" if p.startswith("local:") else p)
    return name + (" (%s)" % sess["client"] if sess.get("client") else "")


def _privacy(priv):
    """Camera / microphone in-use indicators (privacy.status). Shown
    first, highlighted, for as long as a use session is open."""
    if not priv:
        return []
    out = []
    for kind, icon, ko, en in (("camera", "camera-web-symbolic", "카메라 사용 중", "Camera in use"),
                               ("microphone", "audio-input-microphone-symbolic", "마이크 사용 중",
                                "Microphone in use")):
        ss = [x for x in priv.get("sessions", []) if x.get("kind") == kind]
        if ss:
            out.append({"id": "inuse-" + kind, "icon": icon, "text": ko, "alert": True,
                        "tooltip": "%s / %s: %s. 클릭: 권한 / Click: permissions" % (ko, en, ", ".join(_who(x) for x in ss))})
    return out


def _update(up):
    """OS update indicator: an update is available, or one is staged and
    needs a restart. Nothing when up to date (or update.status missing)."""
    if not up:
        return None
    if up.get("restart_needed"):
        return {"id": "update", "icon": "system-reboot-symbolic", "text": "다시 시작 필요",
                "tooltip": "업데이트가 준비됐습니다. 다시 시작하면 적용됩니다 / Update ready: restart to use it. "
                           "클릭: 업데이트 / Click: Update"}
    if up.get("available"):
        v = up.get("available_version") or ""
        return {"id": "update", "icon": "software-update-available-symbolic", "text": "업데이트", "alert": True,
                "tooltip": "OS 업데이트가 있습니다 %s / OS update available %s. 클릭: 업데이트 / Click: Update" % (v, v)}
    return None


def clock(now=None):
    t = time.localtime(now)
    return {"id": "clock", "icon": None, "text": time.strftime("%H:%M", t),
            "tooltip": time.strftime("%Y-%m-%d (%a) %H:%M", t)}


def items(call=rpc, now=None):
    """Status items in display order; missing data drops the item."""
    audio = call("audio.status")
    out = _privacy(call("privacy.status")) + [
        _storage(call("storage.list")), _printing(call("printers.list")), _network(call("network.status")), _vpn(call("network.connections.list")), _bluetooth(call("bluetooth.status")),
        _mic(audio), _volume(audio), _power_mode(call("power.profile.status")), _battery(call("power.status")),
        _update(call("update.status")), clock(now)]
    return [i for i in out if i]
