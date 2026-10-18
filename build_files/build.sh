#!/bin/bash

set -ouex pipefail

# Copy system_files/ from the build context onto the image root.
cp -avf "/ctx/system_files"/. /

dnf5 install -y \
    tmux \
    htop \
    sway \
    firefox \
    flatpak \
    fuzzel \
    google-noto-sans-cjk-ttc-fonts \
    xdg-utils \
    fuse \
    fuse-libs \
    curl

# Brand /usr/lib/os-release (the file /etc/os-release points at) while
# leaving ID and ID_LIKE as fedora. Package managers and bootc key off ID.
sed -i \
    -e 's/^NAME=.*/NAME="Grok Bot OS"/' \
    -e 's/^PRETTY_NAME=.*/PRETTY_NAME="Grok Bot OS"/' \
    /usr/lib/os-release

# fedora-bootc already sets VARIANT="Container Image". Replace it so the
# booted OS identifies itself as Grok Bot OS. Leave ID=fedora alone.
if grep -q '^VARIANT=' /usr/lib/os-release; then
    sed -i 's/^VARIANT=.*/VARIANT="Grok Bot OS"/' /usr/lib/os-release
else
    echo 'VARIANT="Grok Bot OS"' >>/usr/lib/os-release
fi
if grep -q '^VARIANT_ID=' /usr/lib/os-release; then
    sed -i 's/^VARIANT_ID=.*/VARIANT_ID=grok-bot-os/' /usr/lib/os-release
else
    echo 'VARIANT_ID=grok-bot-os' >>/usr/lib/os-release
fi
if ! grep -q '^HOME_URL=' /usr/lib/os-release; then
    echo 'HOME_URL="https://github.com/head77x/oais"' >>/usr/lib/os-release
fi

systemctl enable podman.socket

# Default browser for anything that is not the kiosk window itself.
# grokbot-open-browser forces a separate Firefox profile and --new-window.
# The kiosk Firefox is --no-remote on its own profile, so an OAuth or
# download URL cannot replace the Grok Bot screen (2026-07-13).
mkdir -p /etc/xdg
cat >/etc/xdg/mimeapps.list <<'EOF'
[Default Applications]
text/html=grokbot-browser.desktop
x-scheme-handler/http=grokbot-browser.desktop
x-scheme-handler/https=grokbot-browser.desktop
x-scheme-handler/about=grokbot-browser.desktop
x-scheme-handler/unknown=grokbot-browser.desktop
EOF
echo 'BROWSER=/usr/local/bin/grokbot-open-browser' >>/etc/environment

# Placeholder, or a real Grok Bot build when GROKBOT_APP_SOURCE / a local
# payload and its checksum are set. See build_files/install-grokbot-app.sh.
/ctx/install-grokbot-app.sh

# Kiosk account, separate from the admin user Anaconda creates at install
# time. The password stays locked; tty1 autologin does not ask for one.
# --create-home writes /var/home at build time, which may not ship.
# system_files/usr/lib/tmpfiles.d/grokbot-home.conf recreates it on boot.
useradd --create-home --shell /usr/local/bin/grokbot-session grokbot
