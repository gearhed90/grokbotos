"""lock.status: screen lock and idle state (read-only)."""
import os
import pwd

from . import paths, procs


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def lock_status(params):
    user = pwd.getpwuid(os.getuid()).pw_name
    state_dir = os.environ.get("GROKBOT_LOCK_STATE_DIR") or "/var/lib/grokbot/lock-pin"
    c = procs.ini([os.environ.get("GROKBOT_IDLE_SYS_CONF") or "/etc/grokbot/idle.conf",
                   os.path.join(paths.config_home(), "grokbot", "idle.conf")], "idle")
    return {
        "pin_set": os.path.isfile(os.path.join(state_dir, user)),
        "setup_skipped": os.path.exists(os.path.join(paths.config_home(), "grokbot", "lock-setup-skipped")),
        "locked": procs.running("swaylock"),
        "idle_running": procs.running("swayidle"),
        "screen_off_s": _int(c.get("screen_off"), 300),
        "lock_s": _int(c.get("lock"), 600),
    }
