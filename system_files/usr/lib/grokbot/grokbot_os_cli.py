#!/usr/bin/python3
"""grokbot-os: command line and MCP front end for grokbotd.

  grokbot-os [--json] methods
  grokbot-os [--json] <method> [key=value ...]     e.g. grokbot-os windows.list
  grokbot-os [--json] call <method> [key=value ...]
  grokbot-os audit [-n N]
  grokbot-os mcp                                    MCP server on stdio

Exit codes: 0 ok, 2 usage / invalid params / permission denied,
1 daemon unreachable or the call failed.
"""
import json
import os
import socket
import sys

sys.path.insert(0, os.environ.get("GROKBOT_LIB", "/usr/lib/grokbot"))
from grokbotd import VERSION, paths  # noqa: E402

PROTOCOL = "2025-06-18"


class Unreachable(RuntimeError):
    pass


class Client:
    def __init__(self, path=None):
        self.path = path or paths.socket_path()
        self.sock = None
        self.n = 0

    def call(self, method, params=None):
        if self.sock is None:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(10)
            try:
                s.connect(self.path)
            except OSError as e:
                raise Unreachable("grokbotd not reachable at %s: %s" % (self.path, e))
            self.sock, self.f = s, s.makefile("rwb")
        self.n += 1
        req = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.f.write((json.dumps(req) + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise Unreachable("grokbotd closed the connection")
        return json.loads(line)


def _coerce(v, typ):
    """key=value strings become the type the schema declares."""
    if typ == "boolean" and v in ("true", "false"):
        return v == "true"
    if typ == "integer":
        try:
            return int(v)
        except ValueError:
            return v
    return v


def parse_kv(args):
    out = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(_usage("expected key=value, got %r" % a))
        k, v = a.split("=", 1)
        out[k] = v
    return out


def typed_params(client, method, raw):
    if not raw:
        return {}
    r = client.call("api.methods")
    props = {}
    for m in r.get("result", {}).get("methods", []):
        if m["name"] == method:
            props = (m.get("params") or {}).get("properties", {})
    return {k: _coerce(v, props.get(k, {}).get("type")) for k, v in raw.items()}


def _usage(msg=None):
    if msg:
        sys.stderr.write("grokbot-os: %s\n" % msg)
    sys.stderr.write(__doc__.split("\n\n", 1)[1])
    return 2


def human(value, indent=0):
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (pad, k))
                lines.extend(human(v, indent + 1))
            else:
                lines.append("%s%s: %s" % (pad, k, _scalar(v)))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                sub = human(item, indent + 1)
                if sub:
                    sub[0] = pad + "- " + sub[0].lstrip()
                lines.extend(sub)
            else:
                lines.append("%s- %s" % (pad, _scalar(item)))
    else:
        lines.append(pad + _scalar(value))
    return lines


def _scalar(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def run_call(method, params, as_json):
    try:
        c = Client()
        resp = c.call(method, typed_params(c, method, params))
    except Unreachable as e:
        if as_json:
            print(json.dumps({"ok": False, "error": {"code": "unreachable", "message": str(e)}}))
        else:
            sys.stderr.write("grokbot-os: %s\n" % e)
        return 1
    if "error" in resp:
        err = resp["error"]
        if as_json:
            print(json.dumps({"ok": False, "error": err}, ensure_ascii=False))
        else:
            sys.stderr.write("grokbot-os: %s (%s)\n" % (err.get("message"), err.get("code")))
        return 2 if err.get("code") in (-32601, -32602, -32001) else 1
    if as_json:
        print(json.dumps({"ok": True, "result": resp["result"]}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(human(resp["result"])))
    return 0


def cmd_audit(args, as_json):
    n = 20
    if args[:1] == ["-n"] and len(args) == 2 and args[1].isdigit():
        n = int(args[1])
    elif args:
        return _usage("usage: audit [-n N]")
    try:
        with open(paths.audit_path(), encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except FileNotFoundError:
        lines = []
    for line in lines:
        if as_json:
            sys.stdout.write(line)
        else:
            e = json.loads(line)
            print("%s %-6s %-5s %-24s %s" % (e.get("ts"), e.get("transport", "-"),
                  e.get("decision", e.get("event", "-")), e.get("method", "-"), e.get("principal", "")))
    return 0


# ---------------- MCP (stdio, newline-delimited JSON-RPC) ----------------

def _tool_name(method):
    return method.replace(".", "_")


def mcp_serve(inp=sys.stdin, out=sys.stdout):
    client = Client()
    tools = None

    def send(msg):
        out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        out.flush()

    def load_tools():
        r = client.call("api.methods")
        if "error" in r:
            raise Unreachable(r["error"]["message"])
        return {_tool_name(m["name"]): m for m in r["result"]["methods"]}

    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # notifications (notifications/initialized, cancelled)
        try:
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": (msg.get("params") or {}).get("protocolVersion", PROTOCOL),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "grokbot-os", "version": VERSION},
                    "instructions": "Read-only Grok Bot OS API (phase 1): system, windows, "
                                    "workspaces, docks, wallpaper, apps, power, network."}})
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "tools/list":
                tools = load_tools()
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                    {"name": n, "description": m["description"],
                     "inputSchema": m.get("params") or {"type": "object"},
                     "annotations": {"readOnlyHint": True, "openWorldHint": False}}
                    for n, m in sorted(tools.items()) if n != "api_methods"]}})
            elif method == "tools/call":
                p = msg.get("params") or {}
                tools = tools or load_tools()
                m = tools.get(p.get("name"))
                if m is None or p.get("name") == "api_methods":
                    send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602,
                          "message": "unknown tool: %s" % p.get("name")}})
                    continue
                r = client.call(m["name"], p.get("arguments") or {})
                if "error" in r:
                    send({"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [
                        {"type": "text", "text": json.dumps(r["error"], ensure_ascii=False)}]}})
                else:
                    send({"jsonrpc": "2.0", "id": mid, "result": {
                        "content": [{"type": "text", "text": json.dumps(r["result"], ensure_ascii=False)}],
                        "structuredContent": r["result"]}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601,
                      "message": "method not found: %s" % method}})
        except Unreachable as e:
            client = Client()
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(e)}})
    return 0


def main(argv):
    as_json = False
    while argv and argv[0].startswith("--"):
        if argv[0] == "--json":
            as_json = True
        elif argv[0] == "--version":
            print(VERSION)
            return 0
        elif argv[0] == "--help":
            return _usage() and 0
        else:
            return _usage("unknown option %s" % argv[0])
        argv = argv[1:]
    if not argv:
        return _usage()
    cmd, rest = argv[0], argv[1:]
    if cmd == "mcp":
        return mcp_serve()
    if cmd == "audit":
        return cmd_audit(rest, as_json)
    if cmd == "methods":
        return run_call("api.methods", {}, as_json)
    if cmd == "call":
        if not rest:
            return _usage("call needs a method")
        cmd, rest = rest[0], rest[1:]
    if "." not in cmd and rest and "=" not in rest[0]:
        cmd, rest = cmd + "." + rest[0], rest[1:]  # "windows list" == "windows.list"
    return run_call(cmd, parse_kv(rest), as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
