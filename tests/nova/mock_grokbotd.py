#!/usr/bin/env python3
"""Fake grokbotd unix socket (read methods only) for DRY_RUN tests. Logs every method called."""
import json, os, socketserver, sys
SOCK = sys.argv[1]
R = {"audio.status": {"available": True, "output": {"volume_percent": 30, "muted": False}},
     "display.brightness": {"available": True, "devices": [{"name": "panel", "percent": 48}]},
     "network.wifi.list": {"networks": [{"ssid": "Home", "signal": 90, "security": "WPA2", "in_use": True},
        {"ssid": "Saved5G", "signal": 70, "security": "WPA2", "in_use": False},
        {"ssid": "CoffeeOpen", "signal": 50, "security": None, "in_use": False},
        {"ssid": "Neighbor", "signal": 40, "security": "WPA2", "in_use": False}]},
     "windows.list": {"windows": [{"id": 10, "app_id": "nova-shell"}, {"id": 21, "app_id": "grokbot-webapp-files"},
                                  {"id": 22, "app_id": "nova-web"}]},
     "update.status": {"booted": {"version": "44.20261023.0"}, "available": False, "staged": None, "restart_needed": False, "last": {"ok": False}},
     "system.resources": {"disks": [{"mount": "/", "total_bytes": 1, "free_bytes": 0}, {"mount": "/var", "total_bytes": 16729894912, "free_bytes": 10193608704}]},
     "power.status": {"batteries": [], "on_ac": True}}
class H(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            q = json.loads(line); m = q["method"]
            print("GBD", m, flush=True)
            r = {"jsonrpc": "2.0", "id": q["id"]}
            r.update({"result": R[m]} if m in R else {"error": {"code": -32601, "message": "write not mocked: " + m}})
            self.wfile.write((json.dumps(r) + "\n").encode())
if os.path.exists(SOCK): os.unlink(SOCK)
socketserver.ThreadingUnixStreamServer(SOCK, H).serve_forever()
