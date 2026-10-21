# Grok Bot OS API (grokbotd), phase 1

`grokbotd` is the local API daemon of Grok Bot OS. It exposes the OS to
web apps, scripts and Grok Bot through one API, defined by one file:

    /usr/share/grokbot/api/os-api.schema.json

The JSON-RPC methods, the `grokbot-os` CLI and the MCP tools all come
from that schema. Phase 1 is **read-only**: nothing in the API changes
the system. The plan for later phases is in the platform audit (web apps
first, Chromium only, `.gbapp` bundles, polkit for privileged actions).

## Methods

| Method | Capability | Returns |
|---|---|---|
| `api.methods` | (none) | Methods, their capability and whether the caller is allowed |
| `system.info` | `system.read` | OS name and version, kernel, hostname, uptime, memory, CPUs, booted bootc image, session |
| `windows.list` | `windows.read` | Windows from the sway tree: id, app_id, title, pid, workspace, focused, fullscreen, floating, rect. Optional param `workspace` |
| `workspaces.list` | `windows.read` | Workspaces: name, num, output, focused, visible, urgent |
| `dock.get` | `desktop.read` | Effective dock config (`/etc/grokbot/dock.conf` + `~/.config/grokbot/dock.conf`) |
| `wallpaper.get` | `desktop.read` | Effective wallpaper, mode and color, and whether the image exists |
| `apps.list` | `apps.read` | `installed` (records written by `grokbot-install`) and `launchers` (visible .desktop entries). Param `include_launchers` (default true) |
| `power.status` | `power.read` | Batteries (capacity, status) and `on_ac` |
| `network.status` | `network.read` | Interfaces (state, MAC, wireless, addresses), default route, `online` |
| `lock.status` | `lock.read` | `pin_set` (never the PIN), `setup_skipped`, `locked`, `idle_running`, `screen_off_s`, `lock_s` |
| `audio.status` | `audio.read` | `available`, `output` and `input`: `volume_percent`, `muted` |
| `display.brightness` | `display.read` | Backlight `devices`: name, brightness, max_brightness, percent |

Errors are JSON-RPC errors:

| Code | Meaning |
|---|---|
| -32700 | Parse error |
| -32600 | Invalid request |
| -32601 | Method not found |
| -32602 | Invalid parameters (checked against the schema) |
| -32001 | Permission denied (`error.data.capability` names the missing capability) |
| -32000 | Backend error (for example, sway is not running) |

## Transports

| Transport | Address | Who | Access |
|---|---|---|---|
| Unix socket | `$XDG_RUNTIME_DIR/grokbot/api.sock` (dir 0700, socket 0600) | The session user: the CLI, MCP, and Grok Bot through local-exec | `SO_PEERCRED` must match the daemon's uid. Every read capability is granted |
| HTTP | `127.0.0.1:7311` only | Web apps | Deny by default, per origin (see below) |

The unix socket protocol is one JSON-RPC 2.0 request per line, with one
response per line.

The HTTP endpoints are:

- `POST /v1/rpc`: JSON-RPC 2.0. `Content-Type: application/json` is required.
- `GET /v1/health`: `{"ok": true, ...}`. Returns no OS data.
- `GET /v1/schema`: the API schema.

## Security model

- **Loopback only.** The HTTP server binds 127.0.0.1, never 0.0.0.0. It runs as a systemd **user** service, never as root (`NoNewPrivileges`, address-family and namespace restrictions, `UMask=0077`).
- **Host check (DNS rebinding).** The `Host` header must be `127.0.0.1:7311`, `localhost:7311` or `<id>.app.localhost:7311`. Any other host gets 403.
- **Deny by default, per origin.** A browser request is identified by its `Origin`. An origin gets exactly the capabilities granted in
  `/etc/grokbot/api-permissions.json` (empty by default) or `~/.config/grokbot/api-permissions.json`:

  ```json
  {"origins": {"http://notes.app.localhost:7311": ["system.read", "desktop.read"]}}
  ```

  `"*"` grants every capability to that origin. Requests with no `Origin` (curl, other local users' processes) and `Origin: null` get no capabilities. Grants are re-read on every call, so editing the file takes effect at once.
- **CORS** headers are sent only to granted origins. Preflight from any other origin returns 403. Because `application/json` is required, a cross-site HTML form cannot send a "simple" request.
- **Limits.** Bodies over 64 KB are rejected. The HTTP access log is off, because the audit log is the record.
- **Audit.** Every call is appended to `~/.local/state/grokbot/audit.jsonl` (mode 0600, rotated at 5 MB to `.1`), whether it was allowed, denied or failed. Each line records the time, transport, principal, method, capability, decision and error. Daemon start and stop are logged too. View the log with `grokbot-os audit`.

Not in phase 1: per-launch tokens for web apps, the consent prompt, write methods, and polkit. All of these are planned for later phases.

## CLI: grokbot-os

```
grokbot-os [--json] methods
grokbot-os [--json] <method> [key=value ...]    # grokbot-os system.info
grokbot-os [--json] <ns> <verb> [key=value ...] # grokbot-os windows list workspace=2
grokbot-os audit [-n N]
grokbot-os mcp                                   # MCP server on stdio
```

- `--json` prints `{"ok": true, "result": ...}` or `{"ok": false, "error": ...}`.
- Exit codes: 0 on success; 2 for an unknown method, invalid parameters or a denied call; 1 when the daemon is unreachable or the call failed.

## MCP

`grokbot-os mcp` is an MCP server (stdio, newline-delimited JSON-RPC, protocol 2025-06-18). It implements `initialize`, `ping`, `tools/list` and `tools/call`. Each API method is a tool, with dots replaced by underscores (`windows_list`), and its `inputSchema` is the method's params schema. All tools carry `readOnlyHint: true`. The server calls the daemon over the unix socket, so it has the user's access and every call is audited.

Grok Bot can use the API today through local-exec, with
`grokbot-os --json <method>`. Whether the Grok Bot desktop app can attach a local stdio MCP server directly is unconfirmed (see the audit).

## Examples

```
$ grokbot-os windows list
$ grokbot-os --json dock.get
$ curl -s 127.0.0.1:7311/v1/health
$ curl -s -H 'Origin: http://notes.app.localhost:7311' -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"system.info"}' 127.0.0.1:7311/v1/rpc
```

The last call returns 403 (-32001) until that origin is granted `system.read`.

## Service

```
systemctl --user status grokbotd
journalctl --user -u grokbotd
```

The build enables the service with `systemctl --global enable`. It finds the sway IPC socket in `$XDG_RUNTIME_DIR` when a call needs it, so it can start before sway. The sway config imports `WAYLAND_DISPLAY`, `SWAYSOCK` and `XDG_DATA_DIRS` into the user manager.

## Files

| Path | Purpose |
|---|---|
| `system_files/usr/share/grokbot/api/os-api.schema.json` | API schema |
| `system_files/usr/lib/grokbot/grokbotd/` | Daemon (python3 standard library only) |
| `system_files/usr/lib/grokbot/grokbot_os_cli.py`, `usr/local/bin/grokbot-os` | CLI and MCP |
| `system_files/usr/local/bin/grokbotd` | Daemon launcher |
| `system_files/usr/lib/systemd/user/grokbotd.service` | User service |
| `system_files/etc/grokbot/api-permissions.json` | Origin grants (empty) |
| `tests/grokbotd/test_grokbotd.py`, `tests/test-grokbotd.sh` | Tests (fake sway IPC) |

Override variables for tests: `GROKBOT_API_SOCK`, `GROKBOT_API_PORT`, `GROKBOT_API_SCHEMA`, `GROKBOT_API_SYS_PERMISSIONS`, `GROKBOT_AUDIT_LOG`, `GROKBOT_LIB`, plus the usual `XDG_*` directories.
