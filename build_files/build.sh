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

# nodejs (bundles npm on Fedora): ClaudeCliProvider/GrokCliProvider
# (orchestrator/providers/claude_cli.py, xai_grok.py) shell out to
# `claude`/`grok`, both npm packages. xdg-utils provides `xdg-open`,
# which `claude login`'s browser auto-launch (and any other CLI that
# tries to open a URL the standard Linux way) depends on -- a bare sway
# session has no desktop environment to provide this or a registered
# default browser, unlike GNOME/KDE.
dnf5 install -y python3 sway foot firefox google-noto-sans-cjk-ttc-fonts nodejs xdg-utils

# Register a browser handler for http(s)/html so `xdg-open <url>` (what
# most CLIs, including `claude`, shell out to for "open this login URL in
# a browser") actually resolves to something, instead of silently failing
# because no desktop environment ever set a default.
#
# NOT firefox.desktop directly: the kiosk's own desktop IS a Firefox
# --kiosk window (webshell_cli.py), already running by the time a login
# flow tries to open a URL. A bare `firefox <url>` gets sent to that
# already-running instance via Firefox's remoting protocol and opens as a
# new TAB in the SAME window (Firefox is single-instance by default) --
# not a separate one webshell/wm.py can detect and close. That's what
# left `claude auth login`'s OAuth success page stuck covering the whole
# kiosk UI with no way back (2026-07-13, docs/DECISIONS.md).
# oais-browser.desktop (system_files/usr/share/applications/) wraps
# `firefox --new-window` instead (system_files/usr/local/bin/oais-open-browser)
# so the login flow's URL always opens as a genuinely new top-level
# window that wm.py's before/after `swaymsg -t get_tree` diff can find.
#
# BROWSER=<the same wrapper> is a second, more direct signal -- some
# tools (e.g. Node's `open` package, which Claude Code's CLI may use)
# check $BROWSER before falling back to xdg-open, and PAM's pam_env
# module (part of the standard `login` flow agetty's autologin invokes)
# applies /etc/environment to every session, including the kiosk one.
mkdir -p /etc/xdg
cat > /etc/xdg/mimeapps.list <<'EOF'
[Default Applications]
text/html=oais-browser.desktop
x-scheme-handler/http=oais-browser.desktop
x-scheme-handler/https=oais-browser.desktop
x-scheme-handler/about=oais-browser.desktop
x-scheme-handler/unknown=oais-browser.desktop
EOF
echo 'BROWSER=/usr/local/bin/oais-open-browser' >> /etc/environment

# Bake the CLIs themselves in at build time (root, full write access to
# the global npm prefix) rather than leaving `npm install -g` to run at
# first connect as the unprivileged `aios` kiosk user. That runtime path
# was tried first and failed on real hardware: `npm install -g` targets
# a root-owned global directory by default, which `aios` can't write to
# (confirmed via the shell UI's log panel: exit code 254, consistent
# with npm's EACCES failure mode for a non-root global install) --
# and even when permissions aren't the issue, doing this at first boot
# adds a real network dependency and a multi-minute wait to what should
# be an instant "click Claude, log in" flow (2026-07-11, docs/DECISIONS.md).
# ensure_ready()'s binary-presence check (`claude --version` /
# `grok --version`) finds these already on PATH and skips the runtime
# install_argv step entirely -- it only still exists as a fallback for
# providers this image doesn't know to bake in ahead of time (the
# "다른 CLI 기반 LLM 직접 추가" / `/llm custom` path).
#
# HOME=/tmp: npm needs a writable $HOME for its cache dir, and root's
# ambient $HOME (/root) isn't usable in this build stage -- confirmed in
# CI: `mkdir '/root'` failed with ENOTDIR. Same root cause as the
# /opt and aios-homedir issues already documented above: this base
# image's /root is (like /home, /opt) an ostree symlink into /var
# (-> var/roothome), and /var isn't populated the way a real booted
# system's is during `podman build` -- only /usr and /etc reliably are.
# /tmp is already a real, writable tmpfs in this RUN step (see the
# Containerfile's `--mount=type=tmpfs,dst=/tmp`), so pointing npm's
# $HOME there for just this command sidesteps the problem instead of
# trying to fix /root itself, which nothing at runtime depends on
# anyway (aios, not root, is the account that actually boots into).
HOME=/tmp npm install -g @anthropic-ai/claude-code @xai-official/grok

mkdir -p /usr/lib/oais
cp -a /ctx/orchestrator /usr/lib/oais/orchestrator

# Dedicated service account for the kiosk session, independent of
# whatever admin username Anaconda's interactive install creates
# (disk_config/iso.toml's kickstart doesn't set one -- it's chosen at
# install time, so nothing here can hardcode it). Shell is the launcher
# script from system_files, not /bin/bash -- it execs straight into sway
# on tty1, no .bash_profile dependency.
#
# --create-home writes /var/home/aios right now, at build time -- which,
# per the /var persistence note above, is NOT guaranteed to make it into
# the shipped image. Don't rely on this alone: the actual guarantee that
# aios has a writable $HOME at boot is
# system_files/usr/lib/tmpfiles.d/oais-aios-home.conf (runs every boot,
# ships under /usr so it always exists). --create-home is kept anyway
# since it's harmless and does work in build/test contexts where /var
# does persist.
useradd --create-home --shell /usr/local/bin/oais-shell-launch aios

# Autologin `aios` on tty1 -- standard systemd getty override pattern.
# (system_files/etc/systemd/system/getty@tty1.service.d/autologin.conf
# already copied into place by the cp -avf above.)
