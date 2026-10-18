"""Sway window-manager glue.

Kept separate from `providers/` (portable, knows nothing about
sway/Wayland) and from `connect.py`'s connection logic. Real bug this
exists to fix: `claude auth login` opens a real Firefox window for the
OAuth flow; once the user finishes, Anthropic's own success page just
says "you can now close this window" and sits there -- but this kiosk's
sway config has no title bar, no window chrome, and (until this file)
no way to actually close anything. The comment in
system_files/etc/sway/config claiming "closing it returns focus to the
kiosk window underneath" was aspirational; nothing made that true
(2026-07-11, docs/DECISIONS.md).

Rather than rely on the user discovering a keyboard shortcut, whatever
new Firefox window a login flow opens gets closed automatically once
that flow's subprocess has finished, by diffing sway's window tree
before and after. Best-effort throughout: swaymsg not being present, no
sway IPC socket (not actually running under sway -- e.g. tests, or
onboarding_cli.py's headless path), malformed output, etc. all just mean
this is skipped, never a reason to fail a connection attempt.
"""

from __future__ import annotations

import json
import subprocess

_SWAYMSG_TIMEOUT = 5


def _run_swaymsg(argv: list[str], run) -> subprocess.CompletedProcess:
    return run(["swaymsg", *argv], capture_output=True, text=True, timeout=_SWAYMSG_TIMEOUT)


def _collect_firefox_ids(node: dict, ids: set[int]) -> None:
    if node.get("app_id") == "firefox" and "id" in node:
        ids.add(node["id"])
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        _collect_firefox_ids(child, ids)


def firefox_window_ids(run=subprocess.run) -> set[int]:
    """Best-effort snapshot of currently open Firefox window IDs. Returns
    an empty set (not an exception) on any failure -- no swaymsg binary,
    not running under sway, unparseable output."""
    try:
        result = _run_swaymsg(["-t", "get_tree"], run)
    except Exception:  # noqa: BLE001 - swaymsg missing/sway not running/etc.
        return set()
    if result.returncode != 0:
        return set()
    try:
        tree = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    ids: set[int] = set()
    _collect_firefox_ids(tree, ids)
    return ids


def close_new_firefox_windows(before_ids: set[int], run=subprocess.run) -> None:
    """Close any Firefox window that exists now but wasn't in
    `before_ids` -- i.e. whatever a login flow just opened. Call this
    right after the flow's subprocess has exited, so the window (success
    page, error page, whatever's left on screen) doesn't just sit there
    blocking the kiosk underneath with no way back to it."""
    after_ids = firefox_window_ids(run=run)
    for new_id in after_ids - before_ids:
        try:
            _run_swaymsg([f"[con_id={new_id}]", "kill"], run)
        except Exception:  # noqa: BLE001 - best-effort, never fail the caller over this
            pass
