#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cfg="${root}/system_files/usr/local/bin/grokbot-dock-config"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export HOME="${tmp}/home" XDG_CONFIG_HOME="${tmp}/home/.config"
export GROKBOT_DOCK_SYS_CONF="${root}/system_files/etc/grokbot/dock.conf"
mkdir -p "$HOME"

fail() { echo "FAIL: $*" >&2; exit 1; }

out=$("$cfg" show)
grep -qx 'bottom = icons' <<<"$out" || fail "default bottom"
grep -qx 'left = off' <<<"$out" || fail "default left"

"$cfg" set left labels
"$cfg" set right icons
"$cfg" set top icons
out=$("$cfg" show)
grep -qx 'left = labels' <<<"$out" || fail "left labels"
grep -qx 'right = icons' <<<"$out" || fail "right icons"
grep -qx 'top = icons' <<<"$out" || fail "top icons"

"$cfg" set left off
grep -qx 'left = off' <<<"$("$cfg" show)" || fail "left off overrides"
[[ $(grep -c '^left' "${XDG_CONFIG_HOME}/grokbot/dock.conf") -eq 1 ]] || fail "duplicate key"

if "$cfg" set top labels 2>/dev/null; then fail "top labels accepted"; fi
if "$cfg" set bottom labels 2>/dev/null; then fail "bottom labels accepted"; fi
if "$cfg" set middle icons 2>/dev/null; then fail "bad edge accepted"; fi
if "$cfg" icon-size 5 2>/dev/null; then fail "bad size accepted"; fi

grep -qx 'status = auto' <<<"$("$cfg" show)" || fail "default status"
"$cfg" status left
grep -qx 'status = left' <<<"$("$cfg" show)" || fail "status left"
if "$cfg" status middle 2>/dev/null; then fail "bad status accepted"; fi

"$cfg" reset
grep -qx 'top = off' <<<"$("$cfg" show)" || fail "reset"

echo "PASS test-grokbot-dock-config.sh"
