# Skill: add or change an OS API method

The reference is [`docs/OS_API.md`](../../docs/OS_API.md).

1. **Schema first:** add the method to `system_files/usr/share/grokbot/api/os-api.schema.json`: name, `description`, `params` (use `enum`, `minimum`/`maximum`, `maxLength`; mark secrets `"x-secret": true`), `result`, `capability`, **`scope`**, **`access`** (`read` or `write`) and **`x-title`** (`["한국어", "English"]`, shown in the consent prompt). The JSON-RPC methods, the `grokbot-os` CLI and the MCP tools are all generated from it.
2. **Scope, not app:** permissions are per OS function. Put the method in an existing scope (`x-scopes`; list in `perms.SCOPES`) or add a scope with a Korean and English name in both places. Reuse or add a capability string for documentation (`audio.write`, …).
3. **Consent:** a write runs only if the caller's mode for the scope is `allow`, or `ask` and the user answers the prompt. Set `"consent": "always"` for anything that must be confirmed every time (power, camera/microphone sessions, permission changes). Sensitive scopes belong in `perms.ALWAYS_ASK`. Never add a blanket grant, and do not give a new scope `allow` in `system_files/etc/grokbot/api-permissions.json` (`local` or `origins`) unless the PR says why.
4. **Backend:** reads in `backends.py` (or a module it imports), writes in `writes.py` (`METHODS`, or `CTX_METHODS` when the backend needs the caller). Never put a secret on a command line (`/proc/*/cmdline` is world-readable): use a 0600 file or stdin. Privileged actions go through logind/polkit, never a root daemon shortcut.
5. **Audit:** every call must reach `audit.py` (`~/.local/state/grokbot/audit.jsonl`), whether allowed, denied or failed. Policy checks live in `policy.py`. Never log secrets.
6. **Tests:** add unit tests in `tests/grokbotd/` (`test_consent.py` for writes), covering allow, deny, the prompt answers (`once`/`always`/`deny`, via the fake prompt `$HOME/consent-answer`) and the audit entry. Backends must call fake tools only (`FAKE_TOOLS` in `test_grokbotd.py`), never the real machine. Run `bash tests/run-tests.sh`.
7. **Docs:** update the method table in `docs/OS_API.md`, and `SECURITY.md` (threat model) if the method crosses a new boundary.
8. **VM check:** boot the image (`vm-testing.md`) and call `grokbot-os <method>` in the VM. Put the output or a screenshot in the PR.
