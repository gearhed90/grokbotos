#!/bin/bash
# Run inside the arm64 bootc build, after build.sh.
# Installs dwrobel kernel-rpi5 (not kernel-rpi4) and stages the files the
# Pi 5 EEPROM reads. bootc owns /boot, so the FAT payload lives under
# /usr/lib/grokbot/rpi5-boot and is copied onto the ESP after
# bootc-image-builder. See PI5-STATUS.md.
set -euo pipefail

# shellcheck disable=SC1091
source /ctx/rpi5-cmdline.sh

arch=$(uname -m)
case "$arch" in
    aarch64 | arm64) ;;
    *)
        echo "rpi5-prepare.sh only runs in an arm64 build (got ${arch})." >&2
        echo "Build with: podman build --arch arm64 -f Containerfile.rpi5" >&2
        exit 1
        ;;
esac

dnf5 install -y dnf5-plugins || dnf5 install -y dnf-plugins-core

dnf5 copr enable -y dwrobel/kernel-rpi
dnf5 copr enable -y dwrobel/bcm283x-firmware-rpi
dnf5 copr enable -y dwrobel/bcm434xx-firmware-rpi

# Prefer the downstream kernel over Fedora's. Best-effort: a dnf5 syntax
# change must not hide a later, clearer install error.
dnf5 config-manager setopt \
    'copr:copr.fedorainfracloud.org:dwrobel:kernel-rpi.priority=50' \
    || echo "warning: could not set kernel-rpi repo priority" >&2

shopt -s nullglob
for repo in /etc/yum.repos.d/*dwrobel*.repo /etc/yum.repos.d/*kernel-rpi*.repo \
    /etc/yum.repos.d/*bcm283x*.repo /etc/yum.repos.d/*bcm434xx*.repo; do
    [[ -f "$repo" ]] || continue
    if grep -q '^priority=' "$repo"; then
        sed -i 's/^priority=.*/priority=50/' "$repo"
    else
        sed -i '/^\[/a priority=50' "$repo"
    fi
done
shopt -u nullglob

to_remove=()
for pkg in kernel kernel-core kernel-modules kernel-modules-core kernel-modules-extra; do
    if rpm -q "$pkg" >/dev/null 2>&1; then
        to_remove+=("$pkg")
    fi
done
if [[ ${#to_remove[@]} -gt 0 ]]; then
    rpm -e --nodeps "${to_remove[@]}"
fi

# Pinned to the kernel the Pi already runs, so an in-place `bootc upgrade`
# keeps the same kernel. Bump it on purpose (and check the copr still has it).
KERNEL_RPI5_EVR=6.18.57-1.rpi5.fc44
dnf5 install -y --disablerepo=fedora-cisco-openh264 \
    "kernel-rpi5-${KERNEL_RPI5_EVR}" \
    "kernel-rpi5-core-${KERNEL_RPI5_EVR}" \
    "kernel-rpi5-modules-${KERNEL_RPI5_EVR}" \
    "kernel-rpi5-modules-extra-${KERNEL_RPI5_EVR}" \
    bcm283x-firmware \
    bcm434xx-firmware \
    dracut

if rpm -q kernel-core >/dev/null 2>&1; then
    echo "Fedora kernel-core is still installed" >&2
    rpm -q kernel-core >&2
    exit 1
fi

if rpm -q kernel-rpi5-core >/dev/null 2>&1; then
    kver=$(rpm -q --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-rpi5-core | head -n 1)
else
    kver=$(rpm -q --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-rpi5 | head -n 1)
fi
case "$kver" in
    *rpi4*)
        echo "refusing ${kver}: that build is the Pi 4 kernel (kernel8.img)" >&2
        exit 1
        ;;
esac
echo "kernel-rpi5 ${kver}"
[[ "$kver" == "${KERNEL_RPI5_EVR}.aarch64" ]] || {
    echo "expected kernel-rpi5 ${KERNEL_RPI5_EVR}, got ${kver}" >&2
    exit 1
}

moddir="/usr/lib/modules/${kver}"
if [[ ! -d "$moddir" && -d "/lib/modules/${kver}" ]]; then
    moddir="/lib/modules/${kver}"
fi
[[ -d "$moddir" ]] || {
    echo "no modules directory for ${kver}" >&2
    exit 1
}

cfg="${moddir}/config"
[[ -f "$cfg" ]] || {
    echo "kernel config missing: ${cfg}" >&2
    exit 1
}
grep -q '^CONFIG_ARM64_16K_PAGES=y$' "$cfg" || {
    echo "kernel-rpi5 is not a 16K-page kernel; Pi 5 needs kernel_2712.img" >&2
    exit 1
}
if grep -q '^# CONFIG_EROFS_FS is not set$' "$cfg"; then
    echo "CONFIG_EROFS_FS is disabled; ostree-prepare-root will fail" >&2
    exit 1
fi
grep -qE '^CONFIG_EROFS_FS=(y|m)$' "$cfg" || {
    echo "CONFIG_EROFS_FS is not y or m" >&2
    exit 1
}

# /root is a symlink to var/roothome in bootc images, and /var is empty at
# build time. dracut-install aborts on the dangling link, leaving out erofs.ko.
mkdir -p /var/roothome

install -D -m 0644 /ctx/rpi5/dracut-rpi5.conf /usr/lib/dracut/dracut.conf.d/50-rpi5.conf
dracut \
    --force \
    --no-hostonly \
    --kver "$kver" \
    --add ostree \
    --add-drivers "erofs overlay nvme sdhci sdhci-pltfm xhci-hcd xhci-pci usbhid usb-storage uas" \
    "${moddir}/initramfs.img"
[[ -f "${moddir}/initramfs.img" ]] || {
    echo "dracut did not write ${moddir}/initramfs.img" >&2
    exit 1
}

stage=/usr/lib/grokbot/rpi5-boot
rm -rf "$stage"
mkdir -p "${stage}/overlays"

kimg=""
for candidate in \
    /boot/efi/kernel_2712.img \
    "${moddir}/vmlinux" \
    "${moddir}/vmlinuz"; do
    if [[ -f "$candidate" ]]; then
        kimg=$candidate
        break
    fi
done
[[ -n "$kimg" ]] || {
    echo "no kernel image under /boot/efi or ${moddir}" >&2
    exit 1
}
cp -a "$kimg" "${stage}/kernel_2712.img"
rpi5_kernel_magic_ok "${stage}/kernel_2712.img" || {
    echo "kernel_2712.img has no ARM64 image magic at offset 0x38" >&2
    exit 1
}
cp -a "${moddir}/initramfs.img" "${stage}/initramfs_2712"

# ostree and bootc only look for a file named vmlinuz next to the modules.
# The rpi5 kernel package ships an uncompressed vmlinux, so give it that name.
if [[ ! -f "${moddir}/vmlinuz" ]]; then
    cp -a "$kimg" "${moddir}/vmlinuz"
fi

shopt -s nullglob
dtbs=("${moddir}/dtb/broadcom/"bcm2712*.dtb)
shopt -u nullglob
if [[ ${#dtbs[@]} -eq 0 ]]; then
    echo "no bcm2712 dtb under ${moddir}" >&2
    exit 1
fi
for dtb in "${dtbs[@]}"; do
    cp -a "$dtb" "${stage}/$(basename "$dtb")"
done
[[ -f "${moddir}/dtb/overlays/vc4-kms-v3d.dtbo" ]] || {
    echo "missing vc4-kms-v3d.dtbo" >&2
    exit 1
}
cp -a "${moddir}/dtb/overlays/." "${stage}/overlays/"

shopt -s nullglob
found_bootcode=0
for blob in \
    /boot/bootcode.bin /boot/efi/bootcode.bin \
    /boot/start*.elf /boot/efi/start*.elf \
    /boot/fixup*.dat /boot/efi/fixup*.dat \
    /usr/lib/kernel/rpi-firmware/bootcode.bin \
    /usr/lib/kernel/rpi-firmware/start*.elf \
    /usr/lib/kernel/rpi-firmware/fixup*.dat; do
    [[ -f "$blob" ]] || continue
    cp -a "$blob" "${stage}/$(basename "$blob")"
    [[ "$(basename "$blob")" == "bootcode.bin" ]] && found_bootcode=1
done
shopt -u nullglob
if [[ "$found_bootcode" -ne 1 ]]; then
    echo "bcm283x-firmware did not stage bootcode.bin" >&2
    rpm -ql bcm283x-firmware >&2 || true
    exit 1
fi
[[ -f "${stage}/bcm2712-rpi-5-b.dtb" ]] || {
    echo "missing bcm2712-rpi-5-b.dtb in the boot payload" >&2
    exit 1
}

install -m 0644 /ctx/rpi5/config.txt "${stage}/config.txt"
# Pi-only desktop bits: DSI panel landscape + touch mapping, dock off.
install -D -m 0644 /ctx/rpi5/sway-rpi5-dsi.conf /etc/sway/grokbot.d/50-rpi5-dsi.conf
sed -i 's/^dock = on$/dock = off/' /etc/grokbot/desktop.conf
grep -q '^dock = off$' /etc/grokbot/desktop.conf || { echo "dock default not set" >&2; exit 1; }
install -m 0644 /ctx/rpi5/cmdline.txt "${stage}/cmdline.txt"

# vcgencmd (built in its own stage, see rpi5-build-vcgencmd.sh): /dev/vcio
# for the video group, and grokbot in video. usermod covers fresh flashes;
# the sysusers line covers in-place updates, where /etc/group is machine-local.
install -D -m 0644 /ctx/rpi5/60-grokbot-vcio.rules /usr/lib/udev/rules.d/60-grokbot-vcio.rules
install -D -m 0644 /ctx/rpi5/grokbot-video.sysusers /usr/lib/sysusers.d/grokbot-video.conf
getent group video >/dev/null || { echo "no video group in the base image" >&2; exit 1; }
[[ " $(id -nG grokbot) " == *" video "* ]] || usermod -aG video grokbot

install -D -m 0755 /ctx/rpi5-sync-cmdline.sh /usr/lib/grokbot/rpi5-sync-cmdline.sh
install -D -m 0644 /ctx/rpi5-cmdline.sh /usr/lib/grokbot/rpi5-cmdline.sh
install -D -m 0644 /ctx/rpi5/grokbot-rpi5-cmdline.service \
    /usr/lib/systemd/system/grokbot-rpi5-cmdline.service
install -D -m 0644 /ctx/rpi5/grokbot-rpi5-cmdline.path \
    /usr/lib/systemd/system/grokbot-rpi5-cmdline.path
# In-place updates: copy the next deployment's kernel, initramfs, dtbs,
# overlays and cmdline onto FAT at shutdown, after ostree finalizes it.
install -D -m 0755 /ctx/rpi5-sync-boot.sh /usr/lib/grokbot/rpi5-sync-boot.sh
install -D -m 0644 /ctx/rpi5/grokbot-rpi5-boot-sync.service \
    /usr/lib/systemd/system/grokbot-rpi5-boot-sync.service
systemctl enable grokbot-rpi5-cmdline.service grokbot-rpi5-cmdline.path \
    grokbot-rpi5-boot-sync.service

if command -v lsinitrd >/dev/null 2>&1; then
    # Capture the listing first: with pipefail, grep -q exits early and
    # lsinitrd dies of SIGPIPE, which made this check fail on a good image.
    initrd_list=$(lsinitrd "${stage}/initramfs_2712")
    if ! grep -q 'erofs.ko' <<<"$initrd_list"; then
        echo "initramfs is missing erofs.ko; ostree-prepare-root will fail" >&2
        exit 1
    fi
fi

# bootc synthesizes /boot at install time. A kernel left here makes
# container lint fail and is not what the EEPROM reads.
if [[ -d /boot ]]; then
    find /boot -mindepth 1 -maxdepth 1 -exec rm -rf {} +
fi
mkdir -p /boot
