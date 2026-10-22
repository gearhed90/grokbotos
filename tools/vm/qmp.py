#!/usr/bin/env python3
"""Send QMP commands to a running tools/vm/vm.sh VM.

usage: qmp.py click X Y        (X, Y in guest pixels, default 1280x800)
       qmp.py raw COMMAND [JSON-ARGS]
"""
import json
import os
import socket
import sys
import time

SOCK = os.path.join(os.environ.get("GBVM_DIR", os.path.join(os.path.dirname(__file__), "..", "..", ".vm")), "qmp.sock")


def q(cmd, args=None):
    s = socket.socket(socket.AF_UNIX)
    s.connect(SOCK)
    f = s.makefile("rw")
    f.readline()
    f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
    f.write(json.dumps({"execute": cmd, "arguments": args or {}}) + "\n"); f.flush()
    r = f.readline(); s.close(); return r


def click(x, y, w=1280, h=800):
    ev = lambda ax, v: {"type": "abs", "data": {"axis": ax, "value": int(v * 32767 / (w if ax == "x" else h))}}
    print(q("input-send-event", {"events": [ev("x", x), ev("y", y)]})); time.sleep(0.5)
    for down in (True, False):
        print(q("input-send-event", {"events": [{"type": "btn", "data": {"down": down, "button": "left"}}]})); time.sleep(0.2)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["click"]:
        click(int(a[1]), int(a[2]))
    elif a[:1] == ["raw"]:
        print(q(a[1], json.loads(a[2]) if len(a) > 2 else None))
    else:
        sys.exit(__doc__)
