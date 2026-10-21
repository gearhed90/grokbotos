#!/bin/bash
# grokbotd daemon, grokbot-os CLI and MCP server (tests/grokbotd/).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
python3 "${root}/tests/grokbotd/test_grokbotd.py"
echo "PASS test-grokbotd.sh"
