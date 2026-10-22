# AGENTS.md

These are the rules for AI agents, Grok Bot included, that work on this repository. Human contributors follow [CONTRIBUTING.md](CONTRIBUTING.md). Agents follow that file too, plus everything below.

## Before you start

- Read the task guide in [`agents/skills/`](agents/skills/) that matches your task:
  - [`os-api-methods.md`](agents/skills/os-api-methods.md): add or change a grokbotd OS API method
  - [`vm-testing.md`](agents/skills/vm-testing.md): build the image and boot it in a VM
  - [`visual-verification.md`](agents/skills/visual-verification.md): screenshot and check changed screens
  - [`install-testing.md`](agents/skills/install-testing.md): test installation, the bootloader, UEFI/BIOS/Secure Boot
- Architecture reference is in [`docs/`](docs/). The end-user manual is in [`manual/`](manual/).

## Product rules

- Names: the product is **Grok Bot OS** and the company is **SpaceXSI**. The image names `grokbotos` and `grokbotos-arm64`, `IMAGE_NAME=grokbotos` and the S3 prefix `grokbotos/` (renamed from `oais` on 2026-10-21) **stay unchanged** (see README "Names kept on purpose").
- Commands start with `grokbot-` (e.g. `grokbot-install`, `grokbot-dock-config`).
- **Never put icons on the desktop.** The desktop holds widgets only.
- Docks: top/bottom docks show icons only. Left/right docks show icons, or icons plus labels.
- **Web apps first.** Do not add native apps by default. A native package needs a written reason in the PR.
- Every OS function goes through the **grokbotd OS API** (`docs/OS_API.md`). Do not add side channels. Permissions are **deny-by-default** per caller/origin, and every call is **audited**. A new method needs the schema, a backend, a capability, tests and docs in the same PR (`agents/skills/os-api-methods.md`).

## Engineering rules

- **Do not modify `.github/workflows/`.** Test locally instead: `bash tests/run-tests.sh`, then boot the image in a VM (`agents/skills/vm-testing.md`).
- **Screenshot every screen you changed** and attach the screenshots to the PR (`agents/skills/visual-verification.md`). Say what you did not verify.
- Bash style: `#!/bin/bash`, `set -euo pipefail`, `[[ ]]` for tests, `(( ))` for arithmetic, quote variables, and keep code clean under shellcheck.
- Markdown: no hard wrapping. Write one paragraph per line.
- Never commit secrets, tokens, real passwords or personal test accounts. Pass test credentials through environment variables (e.g. `GBVM_TEST_USER`/`GBVM_TEST_PASS`).
- User-facing text is in Korean and English.

## Changes and merges

- Every change goes through a pull request. Never push to `main`.
- **Only `head77x` approves and merges.** Agents never merge, even if they have permission to.
- Keep one logical change per commit. In the PR, state what you verified (tests, VM, screenshots) and what you did not.
