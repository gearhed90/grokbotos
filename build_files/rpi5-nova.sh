#!/bin/bash
# Raspberry Pi 5 image only (Containerfile.rpi5, after rpi5-prepare.sh).
# Nova becomes the main screen: native GTK avatar app + novad, a touch keypad
# lock screen, H.264 video for Firefox, English web apps, a first-boot admin
# password prompt and the Nunito font. See PI5-STATUS.md and docs/NOVA.md.
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
for f in avatar.py glview.py nova_native.py novad.py shell.html lockscene.py pamauth.py nova-web-user.js; do
    install -m 0644 "${src}/${f}" "${nova}/${f}"
done
install -m 0755 "${src}/grokbot-lock-keypad.py" "${nova}/grokbot-lock-keypad.py"
ln -sf "${nova}/grokbot-lock-keypad.py" /usr/local/bin/grokbot-lock-keypad
install -m 0755 "${src}/grokbot-nova" /usr/local/bin/grokbot-nova
install -d -m 0755 /usr/local/sbin
install -m 0755 "${src}/grokbot-set-xai-key" /usr/local/sbin/grokbot-set-xai-key
install -m 0644 "${src}/grokbot-lock.pam" /etc/pam.d/grokbot-lock
install -m 0644 "${src}/novad.service" /usr/lib/systemd/user/novad.service
install -D -m 0644 "${src}/sway-rpi5-nova.conf" /etc/sway/grokbot.d/60-rpi5-nova.conf
python3 -m py_compile "${nova}"/*.py

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

# --- first-boot admin password -------------------------------------------
install -m 0755 "${src}/grokbot-admin-setup" /usr/local/sbin/grokbot-admin-setup
install -m 0644 "${src}/grokbot-admin-setup.service" /usr/lib/systemd/system/grokbot-admin-setup.service
systemctl enable grokbot-admin-setup.service

# --- built-in web apps open in English (each keeps its 한국어 switch) -----
web=/usr/share/grokbot/webapps
for app in files notes player sysmon; do
    js="${web}/${app}/app.js"
    sed -i "s/localStorage.getItem(\"${app}.lang\") || \"ko\"/localStorage.getItem(\"${app}.lang\") || \"en\"/" "$js"
    grep -q "localStorage.getItem(\"${app}.lang\") || \"en\"" "$js" || {
        echo "could not set English default in ${js}" >&2
        exit 1
    }
    sed -i 's/^<html lang="ko">/<html lang="en">/' "${web}/${app}/index.html"
    sed -i 's|<button type="button" id="lang">English</button>|<button type="button" id="lang">한국어</button>|' "${web}/${app}/index.html"
done

# --- Nunito (SIL OFL 1.1, Google Fonts) for the avatar's z's and the lock --
install -D -m 0644 "${ctx}/rpi5/fonts/Nunito[wght].ttf" "/usr/share/fonts/nunito/Nunito[wght].ttf"
install -D -m 0644 "${ctx}/rpi5/fonts/OFL.txt" /usr/share/licenses/nunito/OFL.txt
fc-cache -f /usr/share/fonts/nunito >/dev/null 2>&1 || true

# The Pi's display/touch fixes no longer need a per-user outputs.conf override
# (50-rpi5-dsi.conf maps touch to DSI-2) or the temporary dock pkill.
echo "rpi5-nova: done"
