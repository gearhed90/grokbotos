# Skill: add or change an OS API method

The reference is [`docs/OS_API.md`](../../docs/OS_API.md).

1. **Schema first:** add the method to `system_files/usr/share/grokbot/api/os-api.schema.json` (name, params, result, capability). The JSON-RPC methods, the `grokbot-os` CLI and the MCP tools are all generated from it.
2. **Capability:** reuse an existing one (`system.read`, `windows.read`, …) or add a new one. A write action needs its own capability, separate from the read one.
3. **Deny by default:** do not grant the new capability to anyone in `system_files/etc/grokbot/api-permissions.json` unless the PR says why. Unknown callers and origins get nothing.
4. **Backend:** implement it under `system_files/usr/lib/grokbot/grokbotd/`. Privileged actions go through polkit, never a root daemon shortcut.
5. **Audit:** every call must reach `audit.py` (`~/.local/state/grokbot/audit.jsonl`), whether allowed, denied or failed. Policy checks live in `policy.py`. Never log secrets.
6. **Tests:** add unit tests in `tests/grokbotd/test_grokbotd.py`, covering both the allowed and the denied path. Run `bash tests/run-tests.sh`.
7. **Docs:** update the method table in `docs/OS_API.md`.
8. **VM check:** boot the image (`vm-testing.md`) and call `grokbot-os <method>` in the VM. Put the output or a screenshot in the PR.
