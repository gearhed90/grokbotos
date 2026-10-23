"""printers.* / print.*: CUPS printers and jobs through the CUPS command-line tools.

No admin rights are used: queues come from `lpstat` (including driverless
IPP Everywhere / AirPrint printers CUPS finds on the network, `lpstat -e`),
the default is the user's own (lpoptions -d, ~/.cups/lpoptions), and jobs
are the user's own. Files to print come from the home folder or an open
USB drive with the files-scope path rules. Printer names are checked
against the listed queues before they reach any command line.
"""
import os
import re
import shutil
import subprocess

from . import files
from .backends import BackendError

NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,127}$")
JOB_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,127}-[0-9]{1,9}$")
MAX_PRINT = 64 * 1024 * 1024


def _run(cmd, timeout=15, ok_empty=False):
    if shutil.which(cmd[0]) is None:
        raise BackendError("printing: %s is not installed (CUPS)" % cmd[0])
    env = dict(os.environ, LC_ALL="C")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise BackendError("printing: %s timed out" % cmd[0])
    except OSError as e:
        raise BackendError("printing: %s failed: %s" % (cmd[0], e))
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        if ok_empty and ("No destinations" in msg or not msg):
            return ""
        if "Unable to connect to server" in msg or "Bad file descriptor" in msg:
            raise BackendError("printing: the print service (CUPS) is not running")
        raise BackendError("printing: %s" % (msg.splitlines()[-1][:200] if msg else r.returncode))
    return r.stdout


def _queues():
    """{name: {state, enabled, device}} from `lpstat -p -v`."""
    out = _run(["lpstat", "-p", "-v"], ok_empty=True)
    q = {}
    for line in out.splitlines():
        m = re.match(r"^printer (\S+) (?:is )?(idle|now printing|disabled)", line)
        if m:
            st = {"idle": "idle", "now printing": "printing", "disabled": "stopped"}[m.group(2)]
            q.setdefault(m.group(1), {})["state"] = st
            continue
        m = re.match(r"^device for (\S+): (.+)$", line)
        if m:
            q.setdefault(m.group(1), {})["uri"] = m.group(2).strip()
    return q


def _default():
    out = _run(["lpstat", "-d"], ok_empty=True)
    m = re.search(r"system default destination: (\S+)", out)
    return m.group(1) if m else None


def _discovered():
    out = _run(["lpstat", "-e"], ok_empty=True)
    return [x.strip() for x in out.splitlines() if NAME_RE.match(x.strip())]


def _jobs():
    out = _run(["lpstat", "-o"], ok_empty=True)
    jobs = []
    for line in out.splitlines():
        f = line.split()
        if f and JOB_RE.match(f[0]):
            jobs.append({"id": f[0], "printer": f[0].rsplit("-", 1)[0], "user": f[1] if len(f) > 1 else None,
                         "size": int(f[2]) if len(f) > 2 and f[2].isdigit() else None})
    return jobs


def printers_list(params):
    try:
        q = _queues()
    except BackendError as e:
        return {"available": False, "reason": str(e).replace("printing: ", ""),
                "printers": [], "default": None, "jobs": []}
    names = list(q) + [n for n in _discovered() if n not in q]
    d = _default()
    out = []
    for n in names:
        info = q.get(n, {})
        uri = info.get("uri") or ""
        out.append({"name": n, "state": info.get("state", "idle"), "default": n == d,
                    "driverless": n not in q or uri.startswith(("ipp://", "ipps://", "implicitclass:")),
                    "connection": uri.split(":", 1)[0] if uri else "network"})
    return {"available": True, "printers": out, "default": d, "jobs": _jobs()}


def _printer(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BackendError("bad printer name")
    if name not in _queues() and name not in _discovered():
        raise BackendError("no such printer")
    return name


def printers_set_default(params):
    n = _printer(params["printer"])
    _run(["lpoptions", "-d", n])
    return printers_list({})


def print_file(params):
    n = _printer(params["printer"])
    with files.on_volume(params):
        path = files.resolve(params["path"])
    if not os.path.isfile(path):
        raise BackendError("not a file")
    if os.path.getsize(path) > MAX_PRINT:
        raise BackendError("file is larger than %d MB" % (MAX_PRINT // 1048576))
    copies = int(params.get("copies", 1))
    cmd = ["lp", "-d", n, "-n", str(copies), "-t", os.path.basename(path)[:100]]
    if params.get("sides") in ("one-sided", "two-sided-long-edge"):
        cmd += ["-o", "sides=" + params["sides"]]
    out = _run(cmd + ["--", path], timeout=60)
    m = re.search(r"request id is (\S+)", out)
    return {"printer": n, "job": m.group(1) if m else None}


def print_test_page(params):
    n = _printer(params["printer"])
    page = next((p for p in ("/usr/share/cups/data/testprint", "/usr/share/cups/data/default-testpage.pdf")
                 if os.path.isfile(p)), None)
    if page is None:
        raise BackendError("printing: no CUPS test page installed")
    out = _run(["lp", "-d", n, "-t", "Grok Bot OS test page", "--", page], timeout=60)
    m = re.search(r"request id is (\S+)", out)
    return {"printer": n, "job": m.group(1) if m else None}


def print_job_cancel(params):
    j = params["job"]
    if not isinstance(j, str) or not JOB_RE.match(j):
        raise BackendError("bad job id")
    if j not in [x["id"] for x in _jobs()]:
        raise BackendError("no such job")
    _run(["cancel", j])
    return {"cancelled": j}


METHODS = {
    "printers.list": printers_list,
    "printers.set_default": printers_set_default,
    "print.file": print_file,
    "print.test_page": print_test_page,
    "print.job.cancel": print_job_cancel,
}
