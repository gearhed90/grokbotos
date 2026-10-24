#!/bin/bash
# Raspberry Pi 5 Nova pieces: static checks plus the Python tests (mock xAI,
# mock grokbotd, DRY_RUN novad). No display, root or network needed.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
cd "$root"
nova=build_files/rpi5/nova

for f in avatar.py glview.py nova_native.py novad.py shell.html lockscene.py pamauth.py \
    nova-web-user.js grokbot-lock-keypad.py grokbot-nova grokbot-set-xai-key \
    grokbot-admin-provision grokbot-admin-provision.service novad.service grokbot-lock.pam sway-rpi5-nova.conf; do
    assert_file "${nova}/${f}"
done
assert_file "build_files/rpi5/fonts/Nunito[wght].ttf"
assert_file build_files/rpi5/fonts/OFL.txt
python3 -m py_compile "${nova}"/*.py
bash -n build_files/rpi5-nova.sh "${nova}/grokbot-nova" "${nova}/grokbot-set-xai-key" "${nova}/grokbot-admin-provision" build-pi-image.sh

# Containerfile runs the Nova step after the Pi kernel step and before lint.
a=$(grep -n '^    /ctx/rpi5-prepare.sh' Containerfile.rpi5 | cut -d: -f1)
b=$(grep -n '^    /ctx/rpi5-nova.sh' Containerfile.rpi5 | cut -d: -f1)
c=$(grep -n '^RUN .*bootc container lint' Containerfile.rpi5 | cut -d: -f1)
[[ -n $a && -n $b && -n $c ]] || fail "Containerfile.rpi5 is missing a step"
(( a < b && b < c )) || fail "Containerfile.rpi5 order: prepare ${a}, nova ${b}, lint ${c}"

# Touch Display 2: overlay, landscape, touch on DSI-2 (connector 1 is DSI-2 to Linux).
assert_contains build_files/rpi5/config.txt "dtoverlay=vc4-kms-dsi-ili9881-7inch"
assert_contains build_files/rpi5/sway-rpi5-dsi.conf "output DSI-2 transform 90"
assert_contains build_files/rpi5/sway-rpi5-dsi.conf "input type:touch map_to_output DSI-2"
grep -q 'map_to_output DSI-1' build_files/rpi5/sway-rpi5-dsi.conf && fail "touch mapped to DSI-1"
assert_contains "${nova}/sway-rpi5-nova.conf" 'for_window [app_id="nova-shell"] inhibit_idle none'

# Kiosk starts Nova; the lock comes back at 10 minutes.
assert_contains build_files/rpi5-nova.sh 'GROKBOT_EXEC="/usr/local/bin/grokbot-nova"'
assert_contains build_files/rpi5-nova.sh 'lock = 600'
assert_contains build_files/rpi5-nova.sh 'screen_off = 300'
# shellcheck disable=SC2016
assert_contains system_files/usr/local/bin/grokbot-lock '"$keypad" -f'
assert_contains "${nova}/grokbot-lock.pam" 'auth       include      login'

# The English default edit must still match the web apps' source.
for app in files notes player sysmon; do
    assert_contains "system_files/usr/share/grokbot/webapps/${app}/app.js" "localStorage.getItem(\"${app}.lang\") || \"ko\""
done

# Codecs from RPM Fusion; no password, key or Wi-Fi secret anywhere in the Pi bits.
assert_contains build_files/rpi5-nova.sh 'libavcodec-freeworld'
# shellcheck disable=SC2016
assert_contains build_files/rpi5-nova.sh 'rpmfusion-free-release-${fedora}.noarch.rpm'
if grep -RInE '(psk|password|passwd)[[:space:]]*=[[:space:]]*[^"$[:space:]]' build_files/rpi5 build_files/rpi5-nova.sh build-pi-image.sh; then
    fail "something that looks like a secret is committed"
fi
if find . -path ./.git -prune -o \( -name '*.nmconnection' -o -name 'xai_key' \) -print | grep -q .; then
    fail "a NetworkManager keyfile or key file is in the repo"
fi
# Admin account: Zack chose a fixed gearhed/gearhed admin. Only the hash, from
# an untracked gitignored file, goes in the image; nothing tracked holds it.
assert_contains "${nova}/grokbot-admin-provision" 'usermod -p'
assert_contains build_files/rpi5-nova.sh 'admin.hash'
assert_contains build_files/rpi5-nova.sh 'visudo -cf /etc/sudoers.d/nova-grokbot'
git check-ignore -q "${nova}/admin.hash" || fail "admin.hash is not gitignored"
git ls-files --error-unmatch "${nova}/admin.hash" >/dev/null 2>&1 && fail "admin.hash is committed"
git grep -qE '\$6\$|chpasswd|gearhed:gearhed' -- build_files build-pi-image.sh && fail "a password or hash is committed"
grep -lP '[\x{AC00}-\x{D7A3}]' "${nova}/grokbot-admin-provision" "${nova}/grokbot-admin-provision.service" && fail "Korean text in admin files"

# grokbot-set-xai-key refuses to run without root.
if bash "${nova}/grokbot-set-xai-key" </dev/null 2>/dev/null; then
    fail "grokbot-set-xai-key ran without root"
fi

# Build script: fixed paths, no arguments, outputs under /data/grokbotos-build.
assert_contains build-pi-image.sh 'OUT=/data/grokbotos-build'
assert_contains build-pi-image.sh '(( $# == 0 )) || die "takes no arguments"'
grep -qE '^[[:space:]]*(source|\.)[[:space:]]' build-pi-image.sh && fail "build script sources a file"

python3 tests/nova/test_units.py
python3 tests/nova/run_tests.py
python3 tests/nova/run_voice_tests.py
echo "ok test-rpi5-nova"
