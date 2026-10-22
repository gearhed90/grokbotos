"""Small helpers shared by the session-status backends (read-only)."""
import configparser
import os
import shutil
import subprocess

from . import paths


def running(name, uid=None):
    """True if a process whose comm is `name` runs as `uid` (default: us)."""
    uid = os.getuid() if uid is None else uid
    base = paths.procfs()
    try:
        pids = [p for p in os.listdir(base) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(base, pid, "comm"), encoding="utf-8") as f:
                comm = f.read().strip()
            if comm != name:
                continue
            if os.stat(os.path.join(base, pid)).st_uid == uid:
                return True
        except OSError:
            continue
    return False


def run(cmd, timeout=3):
    """stdout of cmd, or None if the tool is missing or fails."""
    if shutil.which(cmd[0]) is None:
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def ini(files, section):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(files)
    return dict(cp[section]) if cp.has_section(section) else {}
