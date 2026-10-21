#!/bin/bash
# Runtime installer: flatpak (user, Flathub only) and local apps under $HOME.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

if [[ "$(id -u)" -eq 0 ]]; then
    echo "SKIP test-grokbot-install.sh: the helper refuses root"
    exit 0
fi

install_bin="${root}/system_files/usr/local/bin/grokbot-install"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export HOME="${tmp}/home"
mkdir -p "$HOME"
export GROKBOT_LIB="${root}/system_files/usr/lib/grokbot/common.sh"

python=$(command -v python3)
core="${tmp}/core"
fake="${tmp}/bin"
make_core_path "$core"
mkdir -p "$fake"
export FAKE_FLATPAK_LOG="${tmp}/flatpak.log"
touch "$FAKE_FLATPAK_LOG"
cat >"${fake}/flatpak" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "${FAKE_FLATPAK_LOG:?}"
if [[ "${FAKE_FLATPAK_FAIL:-}" == "1" && "$1" == "install" ]]; then
    exit 1
fi
exit 0
EOF
chmod 755 "${fake}/flatpak"
export PATH="${fake}:${core}"

run_fail() {
    RUN_CODE=0
    "$install_bin" "$@" >"${tmp}/stdout" 2>"${tmp}/stderr" || RUN_CODE=$?
}

run_fail --json flatpak 'not an id'
assert_eq "$RUN_CODE" "2"
assert_contains "${tmp}/stdout" "invalid_app_id"

"$install_bin" --json flatpak org.example.App --name "예시 앱" >"${tmp}/ok.json"
assert_contains "${tmp}/ok.json" '"ok":true'
assert_contains "${tmp}/ok.json" '"id":"org.example.App"'
assert_contains "$FAKE_FLATPAK_LOG" "remote-add --user --if-not-exists flathub"
assert_contains "$FAKE_FLATPAK_LOG" "install --user -y flathub org.example.App"
assert_file "${HOME}/.local/share/grokbot/installed/org.example.App.json"

run_fail --json flatpak org.example.App
assert_eq "$RUN_CODE" "2"
assert_contains "${tmp}/stdout" "already_installed"

printf '#!/bin/sh\necho hi\n' >"${tmp}/hello"
"$install_bin" local --id hello --name "안녕" --source "${tmp}/hello" >"${tmp}/local.out"
[[ -x "${HOME}/Apps/hello/hello" ]]
assert_file "${HOME}/.local/share/applications/grokbot-local-hello.desktop"
assert_contains "${HOME}/.local/share/applications/grokbot-local-hello.desktop" "Exec=${HOME}/Apps/hello/hello"
assert_contains "${HOME}/.local/share/applications/grokbot-local-hello.desktop" "Name=안녕"

ln -s "${tmp}/hello" "${tmp}/link"
run_fail local --id linky --name Link --source "${tmp}/link"
assert_eq "$RUN_CODE" "2"
[[ ! -e "${HOME}/Apps/linky" ]]

mkdir -p "${tmp}/tree"
printf '#!/bin/sh\necho run\n' >"${tmp}/tree/run"
run_fail local --id tree --name Tree --source "${tmp}/tree" --exec '../hello'
assert_eq "$RUN_CODE" "2"
[[ ! -e "${HOME}/Apps/tree" ]]

"$install_bin" local --id tree --name Tree --source "${tmp}/tree" --exec run >/dev/null
[[ -x "${HOME}/Apps/tree/run" ]]

mkdir -p "${tmp}/badtree"
ln -s /etc/passwd "${tmp}/badtree/run"
run_fail local --id bad --name Bad --source "${tmp}/badtree" --exec run
assert_eq "$RUN_CODE" "2"
[[ ! -e "${HOME}/Apps/bad" ]]

run_fail local --id 'BadId' --name Bad --source "${tmp}/hello"
assert_eq "$RUN_CODE" "2"

list=$("$install_bin" --json list)
"$python" -c 'import json,sys; json.loads(sys.stdin.read())' <<<"$list"
printf '%s\n' "$list" >"${tmp}/list.json"
assert_contains "${tmp}/list.json" "org.example.App"
assert_contains "${tmp}/list.json" "hello"

"$install_bin" remove hello >/dev/null
[[ ! -e "${HOME}/Apps/hello" ]]
[[ ! -e "${HOME}/.local/share/applications/grokbot-local-hello.desktop" ]]
[[ ! -e "${HOME}/.local/share/grokbot/installed/hello.json" ]]

: >"$FAKE_FLATPAK_LOG"
"$install_bin" --json remove org.example.App >"${tmp}/removed.json"
assert_contains "${tmp}/removed.json" '"removed":true'
assert_contains "$FAKE_FLATPAK_LOG" "uninstall --user -y org.example.App"

export FAKE_FLATPAK_FAIL=1
run_fail --json flatpak org.example.Fail --name Fail
assert_eq "$RUN_CODE" "1"
assert_contains "${tmp}/stdout" "flatpak_failed"
[[ ! -e "${HOME}/.local/share/grokbot/installed/org.example.Fail.json" ]]

echo "PASS test-grokbot-install.sh"
