"""Who is calling, and which origins get CORS.

Principals:
  local:uid=N    a process of the same user on the unix socket
  origin:<o>     a web page, identified by its HTTP Origin header
  http:no-origin an HTTP client that sent no Origin (curl, scripts)
  http:bad-origin an Origin that is not http(s)://host[:port] ("null")

What each principal may do is decided per scope in perms.py.
"""
import os

from . import perms


def allowed(principal, scope, access="read", capability=None):
    """True if the call would go through without a prompt."""
    if scope is None:
        return True
    return perms.mode_for(principal, scope, access, capability)[0] == "allow"


def origin_known(origin):
    return perms.origin_known(origin)


def tcp_peer_uid(peer_port, local_port, proc="/proc"):
    """uid owning the loopback TCP socket that connected to us, or None.

    The HTTP port is reachable by every local user; only our own uid
    may use it, like the unix socket."""
    want_local = ":%04X" % peer_port
    want_remote = ":%04X" % local_port
    try:
        with open(os.path.join(proc, "net", "tcp"), encoding="ascii") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) > 7 and p[1].endswith(want_local) and p[2].endswith(want_remote):
                    return int(p[7])
    except (OSError, ValueError, StopIteration):
        return None
    return None
