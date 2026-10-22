#!/usr/bin/python3
"""Alt+Tab across every window on every workspace (sway's own `focus next`
stays inside one workspace, and each app opens on its own workspace).
Docks and fuzzel are layer-shell surfaces, not windows, so they are skipped."""
import json
import subprocess
import sys


def views(n, acc):
    if n.get("type") in ("con", "floating_con") and n.get("pid") \
            and not n.get("nodes") and not n.get("floating_nodes"):
        acc.append(n)
    for k in ("nodes", "floating_nodes"):
        for c in n.get(k, []):
            views(c, acc)
    return acc


step = -1 if (len(sys.argv) > 1 and sys.argv[1] == "prev") else 1
tree = json.loads(subprocess.run(["swaymsg", "-r", "-t", "get_tree"],
                                 capture_output=True, text=True).stdout or "{}")
vs = views(tree, [])
if not vs:
    sys.exit(0)
idx = next((i for i, v in enumerate(vs) if v.get("focused")), -1)
target = vs[(idx + step) % len(vs)]
subprocess.run(["swaymsg", f"[con_id={target['id']}] focus"], capture_output=True)
