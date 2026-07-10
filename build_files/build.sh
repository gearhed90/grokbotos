#!/bin/bash

set -ouex pipefail

# Copy the contents of system_files/ of the git repo to /
cp -avf "/ctx/system_files"/. /

# this installs packages from fedora repos
dnf5 install -y tmux htop

# Brand /usr/lib/os-release (the file /etc/os-release symlinks to on bootc
# images) with the project identity, while keeping ID/ID_LIKE as fedora so
# package tooling and `bootc` itself keep working correctly.
sed -i \
  -e "s/^NAME=.*/NAME=\"AI-OS\"/" \
  -e "s/^PRETTY_NAME=.*/PRETTY_NAME=\"AI-OS\"/" \
  /usr/lib/os-release

if ! grep -q '^VARIANT=' /usr/lib/os-release; then
  {
    echo 'VARIANT="AI-OS"'
    echo 'VARIANT_ID=ai-os'
    echo 'HOME_URL="https://github.com/head77x/oais"'
  } >> /usr/lib/os-release
fi

systemctl enable podman.socket

### Phase 4 -- boot-to-shell kiosk session
###
### `claude login`/`grok login` need a real local browser to complete
### (Claude: always, no headless flow yet; Grok: not strictly, but this
### keeps both providers on the same UX) -- see docs/DECISIONS.md. So a
### minimal graphical session is baked in specifically to run one thing
### fullscreen: Firefox in --kiosk mode against a small local HTTP
### server (orchestrator.webshell) that serves the actual shell UI --
### prompt bar + installed-app/LLM-connection icon dock, not a terminal
### menu (see orchestrator/orchestrator/webshell/). Any other Firefox
### window it opens along the way (e.g. an OAuth login redirect) gets
### fullscreened too and returns focus to the kiosk page once closed.
### This is NOT a desktop environment -- no panel, no app launcher, no
### window chrome, nothing but that one app. `foot` is kept installed for
### headless/recovery use (`onboarding_cli.py`'s text flow still works),
### it's just not what boots by default anymore.
###
### google-noto-sans-cjk-ttc-fonts: without a CJK-capable font, Korean
### text (the shell UI's own labels, any Korean the user types back)
### renders as empty boxes -- confirmed on real hardware before this was
### added.
###
### Everything this needs to survive a reboot is placed under /usr or
### /etc on purpose: /opt and /home are symlinked to /var/opt and
### /var/home on this (ostree/bootc) image, and /var content written
### during the image build isn't guaranteed to ship in the committed
### image -- only /usr (read-only, image-provided) and /etc (tracked and
### 3-way-merged by ostree) reliably do. The app lives at
### /usr/lib/oais/orchestrator; sway's config is the system-wide
### /etc/sway/config (system_files/etc/sway/config) rather than a
### per-user ~/.config; the kiosk user's login shell is a launcher script
### under /usr/local/bin (system_files/usr/local/bin/oais-shell-launch)
### rather than relying on a persisted ~/.bash_profile.
###
### UNVERIFIED end-to-end: this dev sandbox has no display to boot-test
### against. Written from documented systemd/sway autologin patterns and
### the /var persistence constraint above; expect to iterate once
### actually booted (docs/LOCAL_SETUP.md).

dnf5 install -y python3 sway foot firefox google-noto-sans-cjk-ttc-fonts

mkdir -p /usr/lib/oais
cp -a /ctx/orchestrator /usr/lib/oais/orchestrator

# Dedicated service account for the kiosk session, independent of
# whatever admin username Anaconda's interactive install creates
# (disk_config/iso.toml's kickstart doesn't set one -- it's chosen at
# install time, so nothing here can hardcode it). Shell is the launcher
# script from system_files, not /bin/bash -- it execs straight into sway
# on tty1, no .bash_profile dependency.
useradd --create-home --shell /usr/local/bin/oais-shell-launch aios

# Autologin `aios` on tty1 -- standard systemd getty override pattern.
# (system_files/etc/systemd/system/getty@tty1.service.d/autologin.conf
# already copied into place by the cp -avf above.)
