#!/bin/bash
# Set the screen-lock PIN of the calling kiosk user. Runs as root via
# /etc/sudoers.d/grokbot-lock; the only allowed caller is the session user.
# stdin: line 1 = new PIN. If a PIN is already set: line 1 = current PIN,
# line 2 = new PIN. The PIN is the user's unix password (swaylock uses PAM).
# Never logs or echoes the PIN.
set -euo pipefail
state_dir=/var/lib/grokbot/lock-pin
user=${SUDO_USER:-}
if [[ -z $user || $user == "root" ]]; then
    echo "lock-setpin: must be run through sudo by the session user" >&2
    exit 2
fi
if ! id -u "$user" >/dev/null 2>&1; then
    echo "lock-setpin: unknown user" >&2
    exit 2
fi
mkdir -p "$state_dir"
chmod 0755 "$state_dir"
marker="$state_dir/$user"

if [[ -f $marker ]]; then
    IFS= read -r current || true
    stored=$(getent shadow "$user" | cut -d: -f2)
    salt=$(cut -d'$' -f3 <<<"$stored")
    check=$(printf '%s' "$current" | openssl passwd -6 -salt "$salt" -stdin)
    if [[ $check != "$stored" ]]; then
        sleep 2
        echo "lock-setpin: current PIN is wrong" >&2
        exit 3
    fi
fi
IFS= read -r pin || true
if (( ${#pin} < 4 || ${#pin} > 64 )); then
    echo "lock-setpin: PIN must be 4-64 characters" >&2
    exit 4
fi
if [[ $pin == *:* ]]; then
    echo "lock-setpin: PIN must not contain ':'" >&2
    exit 4
fi
hash=$(printf '%s' "$pin" | openssl passwd -6 -stdin)
printf '%s:%s\n' "$user" "$hash" | chpasswd -e
date -u +%FT%TZ >"$marker"
chmod 0644 "$marker"
echo "ok"
