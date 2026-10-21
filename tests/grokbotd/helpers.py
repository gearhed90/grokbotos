"""Shared helpers for backend unit tests: temp trees and fake tools."""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SF = os.path.join(ROOT, "system_files")
LIB = os.path.join(SF, "usr", "lib", "grokbot")
BIN = os.path.join(SF, "usr", "local", "bin")
if LIB not in sys.path:
    sys.path.insert(0, LIB)


class Env:
    """Temporary HOME/XDG/proc/sys tree plus a PATH dir for fake tools."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.bin = self.path("bin")
        self.saved = dict(os.environ)
        os.environ.update({
            "HOME": self.root,
            "XDG_CONFIG_HOME": self.path("cfg"),
            "XDG_STATE_HOME": self.path("state"),
            "XDG_DATA_HOME": self.path("data"),
            "XDG_RUNTIME_DIR": self.path("run"),
            "GROKBOT_PROCFS": self.path("proc"),
            "GROKBOT_SYSFS": self.path("sys"),
            "PATH": self.bin + ":" + os.environ.get("PATH", ""),
        })

    def path(self, *p):
        full = os.path.join(self.root, *p)
        os.makedirs(full if not os.path.splitext(full)[1] else os.path.dirname(full), exist_ok=True)
        return full

    def write(self, rel, text, mode=0o644):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(full, mode)
        return full

    def proc(self, pid, comm):
        self.write("proc/%d/comm" % pid, comm + "\n")

    def tool(self, name, script):
        """Fake executable on PATH. script is a bash body."""
        return self.write("bin/" + name, "#!/bin/bash\n" + script + "\n", 0o755)

    def close(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.tmp.cleanup()
