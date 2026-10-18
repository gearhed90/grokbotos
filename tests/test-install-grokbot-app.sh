#!/bin/bash
# Build-time payload installer. No network. Package managers are skipped.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

script="${root}/build_files/install-grokbot-app.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

core="${tmp}/core"
make_core_path "$core"
export PATH="${core}:/usr/bin:/bin"

run() {
    # shellcheck disable=SC2093
    env \
        GROKBOT_DESTDIR="${DESTDIR}" \
        GROKBOT_APP_SOURCE="${GROKBOT_APP_SOURCE:-}" \
        GROKBOT_APP_SHA256="${GROKBOT_APP_SHA256:-}" \
        GROKBOT_APP_KIND="${GROKBOT_APP_KIND:-auto}" \
        GROKBOT_APP_EXEC="${GROKBOT_APP_EXEC:-}" \
        GROKBOT_FLATPAK_ID="${GROKBOT_FLATPAK_ID:-}" \
        GROKBOT_WEB_URL="${GROKBOT_WEB_URL:-}" \
        GROKBOT_LOCAL_PAYLOAD="${GROKBOT_LOCAL_PAYLOAD:-${tmp}/no-payload}" \
        GROKBOT_SHA256SUMS="${GROKBOT_SHA256SUMS:-${tmp}/no-sums}" \
        GROKBOT_SKIP_PACKAGE_INSTALL="${GROKBOT_SKIP_PACKAGE_INSTALL:-}" \
        bash "$script"
}

reset_env() {
    unset GROKBOT_APP_SOURCE GROKBOT_APP_SHA256 GROKBOT_APP_KIND GROKBOT_APP_EXEC
    unset GROKBOT_FLATPAK_ID GROKBOT_WEB_URL GROKBOT_LOCAL_PAYLOAD GROKBOT_SHA256SUMS
    unset GROKBOT_SKIP_PACKAGE_INSTALL
    DESTDIR="${tmp}/root-$$"
}

expect_fail() {
    local code=0
    run >"${tmp}/out" 2>"${tmp}/err" || code=$?
    [[ "$code" -ne 0 ]] || fail "expected failure, got success: $(cat "${tmp}/out" "${tmp}/err")"
}

reset_env
DESTDIR="${tmp}/placeholder"
run >"${tmp}/out"
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="placeholder"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_WEB_URL=""'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_APP_ID="firefox"'
assert_contains "${tmp}/out" "placeholder"

reset_env
DESTDIR="${tmp}/web"
GROKBOT_WEB_URL="https://example.com/grok"
run >/dev/null
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_WEB_URL="https://example.com/grok"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="placeholder"'

reset_env
DESTDIR="${tmp}/bad-url"
# The dollar sign must stay literal so the installer rejects it.
# shellcheck disable=SC2016
GROKBOT_WEB_URL='https://example.com/$(reboot)'
expect_fail
assert_contains "${tmp}/err" "unsafe characters"

reset_env
DESTDIR="${tmp}/ftp"
GROKBOT_WEB_URL="ftp://example.com/grok"
expect_fail

payload="${tmp}/Grok.AppImage"
printf 'grok-bytes\n' >"$payload"
hash=$(sha256sum "$payload" | awk '{print $1}')

reset_env
DESTDIR="${tmp}/no-sum"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_KIND="appimage"
expect_fail
assert_contains "${tmp}/err" "checksum"

reset_env
DESTDIR="${tmp}/bad-sum"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
GROKBOT_APP_KIND="appimage"
expect_fail
assert_contains "${tmp}/err" "checksum mismatch"

reset_env
DESTDIR="${tmp}/appimage"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
run >/dev/null
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="native"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_EXEC="/usr/lib/grokbot/grokbot-native"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_APP_ID="grokbot"'
[[ -x "${DESTDIR}/usr/lib/grokbot/grokbot.AppImage" ]]
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "APPIMAGE_EXTRACT_AND_RUN"
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "/usr/lib/grokbot/grokbot.AppImage"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/http"
GROKBOT_APP_SOURCE="http://example.com/grok.AppImage"
GROKBOT_APP_SHA256="$hash"
expect_fail
assert_contains "${tmp}/err" "https://"

plain="${tmp}/payload"
printf 'plain-bytes\n' >"$plain"
plain_hash=$(sha256sum "$plain" | awk '{print $1}')
printf '%s  payload\n' "$plain_hash" >"${tmp}/SHA256SUMS"

reset_env
DESTDIR="${tmp}/need-kind"
GROKBOT_LOCAL_PAYLOAD="$plain"
GROKBOT_SHA256SUMS="${tmp}/SHA256SUMS"
expect_fail
assert_contains "${tmp}/err" "GROKBOT_APP_KIND"

reset_env
DESTDIR="${tmp}/binary"
GROKBOT_LOCAL_PAYLOAD="$plain"
GROKBOT_SHA256SUMS="${tmp}/SHA256SUMS"
GROKBOT_APP_KIND="binary"
run >/dev/null
[[ -x "${DESTDIR}/usr/lib/grokbot/grokbot" ]]
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/lib/grokbot/grokbot"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/rpm-missing-exec"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="rpm"
GROKBOT_SKIP_PACKAGE_INSTALL=1
expect_fail
assert_contains "${tmp}/err" "GROKBOT_APP_EXEC"

reset_env
DESTDIR="${tmp}/rpm"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="rpm"
GROKBOT_APP_EXEC="/usr/bin/grokbot"
GROKBOT_SKIP_PACKAGE_INSTALL=1
run >/dev/null
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/bin/grokbot"
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="native"'
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/flatpak"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="flatpak"
GROKBOT_FLATPAK_ID="org.example.GrokBot"
GROKBOT_SKIP_PACKAGE_INSTALL=1
run >/dev/null
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/bin/flatpak run org.example.GrokBot"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/flatpak-bad"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="flatpak"
GROKBOT_FLATPAK_ID="not-an-id"
GROKBOT_SKIP_PACKAGE_INSTALL=1
expect_fail

echo "PASS test-install-grokbot-app.sh"
