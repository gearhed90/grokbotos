#!/bin/bash
# Raspberry Pi 5 Nova pieces: static checks plus the Python tests (mock xAI,
# mock grokbotd, DRY_RUN novad). No display, root or network needed.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
cd "$root"
nova=build_files/rpi5/nova

for f in avatar.py avatar_shapes.py glview.py nova_native.py novad.py shell.html lockscene.py pamauth.py \
    nova-web-user.js grokbot-lock-keypad.py grokbot-nova grokbot-set-xai-key cadpad.py grokbot-cadpad-token \
    novad.service grokbot-lock.pam sway-rpi5-nova.conf; do
    assert_file "${nova}/${f}"
done
assert_file "build_files/rpi5/fonts/Nunito[wght].ttf"
assert_file build_files/rpi5/fonts/OFL.txt
python3 -m py_compile "${nova}"/*.py
bash -n build_files/rpi5-nova.sh "${nova}/grokbot-nova" "${nova}/grokbot-set-xai-key" "${nova}/grokbot-cadpad-token" build-pi-image.sh

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
# Grok Bot desktop app starts once at login, behind Nova; no double launch.
assert_file "${nova}/grokbot-desktop-app"
bash -n "${nova}/grokbot-desktop-app"
assert_contains "${nova}/sway-rpi5-nova.conf" 'exec /usr/local/bin/grokbot-desktop-app'
assert_contains "${nova}/grokbot-desktop-app" 'pgrep -u "$(id -u)" -x grok-bot'
assert_contains build_files/rpi5-nova.sh '/usr/local/bin/grokbot-desktop-app'

# Onshape pad: installed, fullscreen rule, LAN target defaults, token never in the image.
assert_contains build_files/rpi5-nova.sh 'cadpad.py'
assert_contains build_files/rpi5-nova.sh '/etc/grokbot/cadpad.conf'
assert_contains build_files/rpi5-nova.sh 'HOST=192.168.12.126'
assert_contains "${nova}/sway-rpi5-nova.conf" 'for_window [app_id="nova-cadpad"] fullscreen enable'
if find . -path ./.git -prune -o \( -name 'cadpad.token' -o -name 'token' \) -print | grep -q .; then
    fail "a pad token file is in the repo"
fi
if printf 'not-a-token\n' | bash "${nova}/grokbot-cadpad-token" >/dev/null 2>&1; then
    fail "grokbot-cadpad-token accepted a bad token"
fi

# Kiosk starts Nova; the lock comes back at 10 minutes.
assert_contains build_files/rpi5-nova.sh 'GROKBOT_EXEC="/usr/local/bin/grokbot-nova"'
assert_contains build_files/rpi5-nova.sh 'lock = 600'
assert_contains build_files/rpi5-nova.sh 'screen_off = 300'
# shellcheck disable=SC2016
assert_contains system_files/usr/local/bin/grokbot-lock '"$keypad" -f'
assert_contains "${nova}/grokbot-lock.pam" 'auth       include      login'

# English is the default UI language in the sources themselves (Korean stays
# one click away); the Pi build no longer patches it in with sed.
for app in files notes player sysmon; do
    assert_contains "system_files/usr/share/grokbot/webapps/${app}/app.js" "localStorage.getItem(\"${app}.lang\") || \"en\""
    assert_contains "system_files/usr/share/grokbot/webapps/${app}/index.html" '<html lang="en">'
    assert_contains "system_files/usr/share/grokbot/webapps/${app}/manifest.json" '"lang": "en"'
done
assert_contains system_files/usr/share/grokbot/webapps/settings/app.js 'localStorage.getItem("lang") === "ko" ? "ko" : "en"'
assert_contains system_files/usr/share/grokbot/webapps/settings/index.html '<html lang="en">'
assert_contains system_files/usr/local/bin/grokbot-settings '"intl.accept_languages", "en-US, en, ko-KR, ko"'
assert_contains system_files/usr/local/bin/grokbot-webapp '"intl.accept_languages", "en-US, en, ko-KR, ko"'
for d in system_files/usr/share/applications/grokbot-*.desktop; do
    if grep -qP '^(Name|Comment)=.*[\x{AC00}-\x{D7A3}]' "$d"; then
        fail "${d}: the default Name/Comment is Korean (use Name[ko]=)"
    fi
done
if grep -q 'lang") || "ko"' build_files/rpi5-nova.sh; then
    fail "rpi5-nova.sh still patches the web app language"
fi

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
# No built-in admin account (no default admin/password).
[[ ! -e "${nova}/grokbot-admin-provision" ]] || fail "grokbot-admin-provision is back"
grep -q 'grokbot-admin-provision' build_files/rpi5-nova.sh && fail "rpi5-nova.sh still installs grokbot-admin-provision"
grep -q 'chpasswd' build_files/rpi5-nova.sh && fail "rpi5-nova.sh sets a password"
assert_contains build_files/rpi5-nova.sh 'local-nova-sudo'
git ls-files --error-unmatch "${nova}/local-nova-sudo" >/dev/null 2>&1 && fail "local-nova-sudo is committed"

# grokbot-set-xai-key refuses to run without root.
if bash "${nova}/grokbot-set-xai-key" </dev/null 2>/dev/null; then
    fail "grokbot-set-xai-key ran without root"
fi

# Build script: fixed paths, no arguments, outputs under /data/grokbotos-build.
assert_contains build-pi-image.sh 'OUT=/data/grokbotos-build'
assert_contains build-pi-image.sh '(( $# == 0 )) || die "takes no arguments"'
grep -qE '^[[:space:]]*(source|\.)[[:space:]]' build-pi-image.sh && fail "build script sources a file"

# Cypher (cypherd): installed, enabled per user, locked limits shipped, no token in the image.
cy=build_files/rpi5/cypher
for f in cypherd.py cypherd.service cypher-limits.json persona.md grokbot-cypher grokbot-set-cypher-token; do
    assert_file "${cy}/${f}"
done
bash -n "${cy}/grokbot-set-cypher-token"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${cy}/cypher-limits.json"
assert_contains build_files/rpi5-nova.sh 'systemctl --global enable cypherd.service'
assert_contains build_files/rpi5-nova.sh '/etc/grokbot/cypher-limits.json'
assert_contains build_files/rpi5-nova.sh '[[ ! -e /etc/grokbot/cypher-brain-token ]]'
assert_contains build_files/rpi5-nova.sh 'systemctl enable tailscaled.service'
assert_contains "${cy}/cypherd.service" 'RestartPreventExitStatus=78'
assert_contains "${cy}/cypherd.service" 'MemoryMax='
if bash "${cy}/grokbot-set-cypher-token" </dev/null 2>/dev/null; then
    fail "grokbot-set-cypher-token ran without root"
fi
# The on-screen assistant is Cypher now (was Pixel).
assert_contains "${nova}/novad.py" 'You are Cypher, the assistant'
assert_contains "${nova}/shell.html" 'placeholder="Ask Cypher…"'
if grep -n 'Pixel' "${nova}"/*.py "${nova}"/*.html | grep -v devicePixelRatio; then
    fail "the assistant is still called Pixel somewhere"
fi
python3 tests/cypher/test_cypherd.py

python3 tests/nova/test_units.py
python3 tests/nova/run_tests.py
python3 tests/nova/test_vad.py
python3 tests/nova/run_voice_tests.py
python3 tests/nova/test_cadpad.py
echo "ok test-rpi5-nova"
