"""Who may call what. Deny by default.

Principals:
  local:uid=N   a process of the same user on the unix socket
  origin:<o>    a web page, identified by its HTTP Origin header
  http:no-origin an HTTP client that sent no Origin (curl, scripts)

The unix socket is reachable only by the owning user (0700 dir, 0600
socket, SO_PEERCRED check), so same-uid callers get every read
capability. Web origins get only what api-permissions.json grants:

  {"origins": {"http://notes.app.localhost:7311": ["system.read"]}}

"*" grants every capability to that origin. No entry, no access.
Methods whose capability is null (api.methods) are open to any caller
that passed transport checks.
"""
import json
import os

from . import paths


def _load_grants():
    grants = {}
    for p in paths.permissions_paths():
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            continue  # a broken file grants nothing
        origins = doc.get("origins") if isinstance(doc, dict) else None
        if not isinstance(origins, dict):
            continue
        for origin, caps in origins.items():
            if isinstance(origin, str) and isinstance(caps, list):
                grants.setdefault(origin, set()).update(
                    c for c in caps if isinstance(c, str))
    return grants


def allowed(principal, capability):
    if capability is None:
        return True
    if principal.startswith("local:uid="):
        return principal == "local:uid=%d" % os.getuid()
    if principal.startswith("origin:"):
        caps = _load_grants().get(principal[len("origin:"):], set())
        return "*" in caps or capability in caps
    return False


def origin_known(origin):
    return origin in _load_grants()
