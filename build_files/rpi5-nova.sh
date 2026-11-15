#!/bin/bash
# Raspberry Pi 5 image only (Containerfile.rpi5, after rpi5-prepare.sh).
# Nova becomes the main screen: native GTK avatar app + novad, a touch keypad
# lock screen, H.264 video for Firefox, English web apps and the Nunito
# font (no built-in admin account). See PI5-STATUS.md and docs/NOVA.md.
# Never puts a key, password or Wi-Fi secret in the image.
set -euo pipefail
ctx=${GROKBOT_CTX:-/ctx}
src="${ctx}/rpi5/nova"
nova=/usr/share/grokbot/nova

# --- packages -------------------------------------------------------------
# gtk4 + gtk4-layer-shell: ext-session-lock for the keypad lock (the GTK3
# gtk-layer-shell in the image has no session-lock API). pam is already there.
# RPM Fusion free: libavcodec-freeworld adds H.264/H.265/AAC to Firefox's
# ffmpeg decoder (Fedora's own ffmpeg-free leaves them out). The Pi 5 has no
# H.264 hardware decoder, so this is software decoding.
fedora=$(rpm -E %fedora)
dnf5 install -y --disablerepo=fedora-cisco-openh264 \
    "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${fedora}.noarch.rpm"
dnf5 install -y --disablerepo=fedora-cisco-openh264 \
    gtk4 gtk4-layer-shell python3-cairo curl libavcodec-freeworld
rpm -q libavcodec-freeworld gtk4-layer-shell >/dev/null
[[ -f /usr/lib64/girepository-1.0/Gtk4SessionLock-1.0.typelib ]] || {
    echo "gtk4-layer-shell has no Gtk4SessionLock typelib" >&2
    exit 1
}

# --- Nova app + novad -----------------------------------------------------
install -d -m 0755 "$nova"
for f in avatar.py avatar_shapes.py glview.py nova_native.py novad.py shell.html lockscene.py pamauth.py cadpad.py nova-web-user.js; do
    install -m 0644 "${src}/${f}" "${nova}/${f}"
done
install -m 0755 "${src}/grokbot-lock-keypad.py" "${nova}/grokbot-lock-keypad.py"
ln -sf "${nova}/grokbot-lock-keypad.py" /usr/local/bin/grokbot-lock-keypad
install -m 0755 "${src}/grokbot-nova" /usr/local/bin/grokbot-nova
install -m 0755 "${src}/grokbot-desktop-app" /usr/local/bin/grokbot-desktop-app
install -m 0755 "${src}/grokbot-cadpad-token" /usr/local/bin/grokbot-cadpad-token
# Onshape pad (cadpad.py -> onshape-pad-helper on the CAD PC over the LAN).
# Host and port only; the shared token is never in the image (each user saves
# it with grokbot-cadpad-token into ~/.config/grokbot/cadpad.token, 0600).
install -d -m 0755 /etc/grokbot
cat >/etc/grokbot/cadpad.conf <<'CONF'
# Onshape pad target (onshape-pad-helper). Override in ~/.config/grokbot/cadpad.conf.
HOST=192.168.12.126
PORT=8790
CONF
install -d -m 0755 /usr/local/sbin
install -m 0755 "${src}/grokbot-set-xai-key" /usr/local/sbin/grokbot-set-xai-key
install -m 0644 "${src}/grokbot-lock.pam" /etc/pam.d/grokbot-lock
install -m 0644 "${src}/novad.service" /usr/lib/systemd/user/novad.service
install -D -m 0644 "${src}/sway-rpi5-nova.conf" /etc/sway/grokbot.d/60-rpi5-nova.conf
python3 -m py_compile "${nova}"/*.py

# --- Cypher: autonomy loop (cypherd) -----------------------------------------
# Drives, a 45 s decision tick and a journal; thinks with Alpha's llama-server
# through cypher-brain-proxy (cameras first), hosted Grok backup under a daily
# cap. /etc/grokbot/cypher-limits.json is the locked limits file (root-owned;
# cypherd refuses to run if it is missing or writable by others). The proxy
# token is never in the image: sudo grokbot-set-cypher-token saves it as
# /etc/grokbot/cypher-brain-token (root:grokbot 0640). See docs/CYPHER.md.
csrc="${ctx}/rpi5/cypher"
cypher=/usr/share/grokbot/cypher
install -d -m 0755 "$cypher"
install -m 0644 "${csrc}/cypherd.py" "${cypher}/cypherd.py"
install -m 0644 "${csrc}/persona.md" "${cypher}/persona.md"
install -m 0644 "${csrc}/cypher-limits.json" /etc/grokbot/cypher-limits.json
install -m 0755 "${csrc}/grokbot-cypher" /usr/local/bin/grokbot-cypher
install -m 0755 "${csrc}/grokbot-set-cypher-token" /usr/local/sbin/grokbot-set-cypher-token
install -m 0644 "${csrc}/cypherd.service" /usr/lib/systemd/user/cypherd.service
systemctl --global enable cypherd.service
python3 -m py_compile "${cypher}/cypherd.py"
[[ ! -e /etc/grokbot/cypher-brain-token ]]

# Phase 2: local fallback model, a podman quadlet on the official llama.cpp
# server image (pinned by digest; ~3x faster on the Pi 5 than Fedora's generic
# llama-cpp build). The 2 GB model is not in the image (it would ride along with
# every update) but fetched once into /var by cypher-llm-fetch (sha256-pinned).
# cypher-llm serves it on 127.0.0.1:8081 under a 3 GB memory cap and 3 CPUs.
install -D -m 0755 "${csrc}/cypher-llm-fetch" /usr/libexec/grokbot/cypher-llm-fetch
install -D -m 0644 "${csrc}/cypher-llm.container" /usr/share/containers/systemd/cypher-llm.container
install -m 0644 "${csrc}/cypher-llm-fetch.service" /usr/lib/systemd/system/cypher-llm-fetch.service
install -m 0644 "${csrc}/cypher-llm.tmpfiles" /usr/lib/tmpfiles.d/cypher-llm.conf
systemctl enable cypher-llm-fetch.service

# --- Tailscale (Fedora package): reach Alpha away from home. Not logged in
# here; the owner joins the device to the tailnet with sudo tailscale up.
dnf5 install -y tailscale
systemctl enable tailscaled.service

# Nova replaces the Grok Bot sign-in app as the kiosk screen. Firefox stays
# for web pages (novad's nova-web profile).
cat >/etc/grokbot/app.conf <<'CONF'
# Raspberry Pi 5: Nova (native GTK app) is the main screen. Written by rpi5-nova.sh.
GROKBOT_MODE="native"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="nova-shell"
GROKBOT_EXEC="/usr/local/bin/grokbot-nova"
CONF

# xAI key: none in the image. The admin saves it with sudo grokbot-set-xai-key
# as /etc/grokbot/xai_key (root:grokbot 0640); novad reads that first.
[[ ! -e /etc/grokbot/xai_key ]]

# --- idle: screen off 5 min, auto-lock 10 min (keypad lock) ---------------
cat >/etc/grokbot/idle.conf <<'CONF'
# Grok Bot OS idle defaults (Raspberry Pi 5). Users override in ~/.config/grokbot/idle.conf.
# Seconds. 0 disables that step. Nova itself dozes after 120 s.
[idle]
screen_off = 300
lock = 600
CONF

# --- no built-in admin account (removed 2026-10-30: a default
# admin/password login is not shipped). Admin accounts are made by the
# owner. Optional local Nova sudo ---------------------------------------------
# Passwordless sudo for the grokbot (Nova) user is OFF by default. It is only
# added for a local build that has the untracked, gitignored marker file
# build_files/rpi5/nova/local-nova-sudo (the owner's own Pi).
if [[ -e "${src}/local-nova-sudo" ]]; then
    install -d -m 0750 /etc/sudoers.d
    printf 'grokbot ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/nova-grokbot
    chmod 0440 /etc/sudoers.d/nova-grokbot
    visudo -cf /etc/sudoers.d/nova-grokbot
fi

# --- Nunito (SIL OFL 1.1, Google Fonts) for the avatar's z's and the lock --
install -D -m 0644 "${ctx}/rpi5/fonts/Nunito[wght].ttf" "/usr/share/fonts/nunito/Nunito[wght].ttf"
install -D -m 0644 "${ctx}/rpi5/fonts/OFL.txt" /usr/share/licenses/nunito/OFL.txt
fc-cache -f /usr/share/fonts/nunito >/dev/null 2>&1 || true

# The Pi's display/touch fixes no longer need a per-user outputs.conf override
# (50-rpi5-dsi.conf maps touch to DSI-2) or the temporary dock pkill.
echo "rpi5-nova: done"
