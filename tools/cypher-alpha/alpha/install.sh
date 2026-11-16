#!/usr/bin/bash
# Copy the deck's cypherd (same code, CYPHER_HOST=alpha) and its limits into place for
# cypherd-alpha. Run after pulling a new grokbotos commit. The standby also takes the
# deck's own limits from the sync store once the deck has pushed them.
set -euo pipefail
repo="${GROKBOTOS_REPO:-$HOME/grokbotos-rpi5}/build_files/rpi5/cypher"
here="$(cd "$(dirname "$0")" && pwd)"
install -m 0600 "${repo}/cypherd.py" "${here}/cypherd.py"
install -m 0600 "${repo}/persona.md" "${here}/persona.md"
install -m 0600 "${repo}/cypher-limits.json" "${here}/cypher-limits.json"
git -C "${repo}" rev-parse --short HEAD > "${here}/SOURCE_COMMIT"
echo "cypherd-alpha files from $(cat "${here}/SOURCE_COMMIT")"
