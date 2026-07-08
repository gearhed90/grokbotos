#!/bin/bash

set -ouex pipefail

# Copy the contents of system_files/ of the git repo to /
cp -avf "/ctx/system_files"/. /

### Phase 1 -- Hello World OS
### Minimal customization so we can build -> push -> boot once, end to end,
### before any AI orchestration functionality is added (Phase 2+).

# this installs packages from fedora repos
dnf5 install -y tmux htop

# Brand /usr/lib/os-release (the file /etc/os-release symlinks to on bootc
# images) with the project identity, while keeping ID/ID_LIKE as fedora so
# package tooling and `bootc` itself keep working correctly.
sed -i \
  -e "s/^NAME=.*/NAME=\"AI-OS\"/" \
  -e "s/^PRETTY_NAME=.*/PRETTY_NAME=\"AI-OS (Phase 1 - Hello World)\"/" \
  /usr/lib/os-release

if ! grep -q '^VARIANT=' /usr/lib/os-release; then
  {
    echo 'VARIANT="AI-OS"'
    echo 'VARIANT_ID=ai-os'
    echo 'HOME_URL="https://github.com/head77x/oais"'
  } >> /usr/lib/os-release
fi

#### Example for enabling a System Unit File

systemctl enable podman.socket
