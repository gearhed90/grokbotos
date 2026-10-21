#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
wp="${root}/system_files/usr/local/bin/grokbot-wallpaper"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export HOME="${tmp}/home" XDG_CONFIG_HOME="${tmp}/home/.config"
export GROKBOT_DESKTOP_SYS_CONF="${root}/system_files/etc/grokbot/desktop.conf"
mkdir -p "$HOME"
fail() { echo "FAIL: $*" >&2; exit 1; }

grep -qx 'wallpaper = /usr/share/grokbot/wallpapers/lofoten.jpg' <<<"$("$wp" show)" || fail "default"
[[ -f "${root}/system_files/usr/share/grokbot/wallpapers/lofoten.jpg" ]] || fail "default image missing"
grep -q 'CC0' "${root}/system_files/usr/share/grokbot/wallpapers/CREDITS.md" || fail "credits"

img="${tmp}/my pic.png"
: >"$img"
"$wp" set "$img" fit
out=$("$wp" show)
grep -qx "wallpaper = ${img}" <<<"$out" || fail "set path"
grep -qx 'mode = fit' <<<"$out" || fail "set mode"
"$wp" color '#112233'
grep -qx 'color = #112233' <<<"$("$wp" show)" || fail "color"

if "$wp" set "${tmp}/missing.png" 2>/dev/null; then fail "missing file accepted"; fi
if "$wp" set "$img" sideways 2>/dev/null; then fail "bad mode accepted"; fi
if "$wp" color red 2>/dev/null; then fail "bad color accepted"; fi

"$wp" reset
grep -qx 'mode = fill' <<<"$("$wp" show)" || fail "reset"
echo "PASS test-grokbot-wallpaper.sh"
