#!/usr/bin/env python3
"""Stand-in for xdotool in the Onshape pad tests. State lives in $MOCK_XDO_DIR:
  open      -> an Onshape window (id 111) exists
  active    -> id of the focused window (default 222, some other app)
  nofocus   -> windowactivate does nothing (focus can't be taken)
  keys.log  -> every key/type the helper sent, one per line, with the active window id."""
import os, sys
d = os.environ["MOCK_XDO_DIR"]; a = sys.argv[1:]
def rd(n, default=""):
    try: return open(os.path.join(d, n)).read().strip()
    except OSError: return default
active = rd("active", "222")
if not a: sys.exit(1)
if a[0] == "search":
    if os.path.exists(os.path.join(d, "open")): print("111"); sys.exit(0)
    sys.exit(1)
if a[0] == "getactivewindow":
    print(active); sys.exit(0)
if a[0] == "windowactivate":
    if not os.path.exists(os.path.join(d, "nofocus")):
        open(os.path.join(d, "active"), "w").write(a[-1])
    sys.exit(0)
if a[0] in ("key", "type"):
    with open(os.path.join(d, "keys.log"), "a") as f:
        f.write("%s %s %s\n" % (active, a[0], a[-1]))
    sys.exit(0)
sys.exit(2)
