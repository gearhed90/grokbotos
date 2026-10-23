#!/bin/bash
# Static checks for the Pi 5 EEPROM layout. No disk image is built here.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
# shellcheck source=build_files/rpi5-cmdline.sh
source "${root}/build_files/rpi5-cmdline.sh"
cd "$root"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

write_kernel() {
    local dest="$1"
    python3 - "$dest" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
b = bytearray(64)
b[0:2] = b"MZ"
b[0x38:0x3C] = b"ARMd"
p.write_bytes(b)
PY
}

payload="${tmp}/payload"
mkdir -p "${payload}/overlays"
write_kernel "${payload}/kernel_2712.img"
cp "${root}/build_files/rpi5/config.txt" "${payload}/config.txt"
printf 'unfilled\n' > "${payload}/cmdline.txt"
printf 'dtb\n' > "${payload}/bcm2712-rpi-5-b.dtb"
printf 'ovl\n' > "${payload}/overlays/vc4-kms-v3d.dtbo"
printf 'initrd\n' > "${payload}/initramfs_2712"

rpi5_kernel_magic_ok "${payload}/kernel_2712.img" || fail "ARM64 magic not accepted"
printf 'nope\n' > "${tmp}/bad-kernel"
if rpi5_kernel_magic_ok "${tmp}/bad-kernel"; then
    fail "short file accepted as a kernel"
fi

blsdir="${tmp}/bls/loader/entries"
mkdir -p "$blsdir"
cat > "${blsdir}/ostree-1.conf" <<'EOF'
title Grok Bot OS
version 1
options root=UUID=11111111-2222-3333-4444-555555555555 rw ostree=/ostree/boot.0/fedora/abc/0 /efi/kernel8.img kernel=/efi/kernel8.img
EOF

fat="${tmp}/fat"
mkdir -p "$fat"
rpi5_install_boot "$payload" "$fat" "$blsdir"
assert_file "${fat}/kernel_2712.img"
assert_file "${fat}/overlays/vc4-kms-v3d.dtbo"
assert_contains "${fat}/config.txt" "kernel=kernel_2712.img"
assert_contains "${fat}/cmdline.txt" "root=UUID=11111111-2222-3333-4444-555555555555"
assert_contains "${fat}/cmdline.txt" "ostree=/ostree/boot.0/fedora/abc/0"
assert_contains "${fat}/cmdline.txt" "console=serial0,115200"
assert_contains "${fat}/cmdline.txt" "console=tty1"
assert_contains "${fat}/cmdline.txt" "rootwait"
if grep -q 'kernel8.img' "${fat}/cmdline.txt"; then
    fail "cmdline still names kernel8.img"
fi
if grep -q 'BOOTC_CMDLINE_UNFILLED' "${fat}/cmdline.txt"; then
    fail "placeholder cmdline was installed"
fi
count=$(grep -o 'console=tty1' "${fat}/cmdline.txt" | wc -l)
[[ "$count" -eq 1 ]] || fail "console=tty1 duplicated"

# consoles already present are not duplicated
mkdir -p "${tmp}/bls2"
cat > "${tmp}/bls2/entry.conf" <<'EOF'
options console=serial0,115200 console=tty1 root=UUID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee rw rootwait ostree=/ostree/boot.1/fedora/def/0
EOF
line=$(rpi5_cmdline_from_bls "${tmp}/bls2")
count=$(grep -o 'console=serial0,115200' <<< "$line" | wc -l)
[[ "$count" -eq 1 ]] || fail "serial console duplicated: ${line}"

mkdir -p "${tmp}/fat3"
rm -f "${payload}/kernel_2712.img"
if rpi5_install_boot "$payload" "${tmp}/fat3" "$blsdir"; then
    fail "missing kernel was accepted"
fi
write_kernel "${payload}/kernel_2712.img"

bad="${tmp}/badpayload"
mkdir -p "$bad"
write_kernel "${bad}/kernel_2712.img"
printf 'kernel=/efi/kernel8.img\n' > "${bad}/config.txt"
if rpi5_install_boot "$bad" "${tmp}/fat3" "$blsdir"; then
    fail "Linux kernel path in config.txt was accepted"
fi

printf 'options BOOTC_CMDLINE_UNFILLED root=UUID=abc\n' > "${tmp}/unfilled.conf"
if rpi5_cmdline_from_bls "${tmp}/unfilled.conf"; then
    fail "unfilled marker was accepted"
fi
printf 'options rw ostree=/ostree/boot.0/fedora/abc/0\n' > "${tmp}/noroot.conf"
if rpi5_cmdline_from_bls "${tmp}/noroot.conf"; then
    fail "missing root= was accepted"
fi
printf 'options root=/dev/mmcblk0p2 rw\n' > "${tmp}/devnode.conf"
if rpi5_cmdline_from_bls "${tmp}/devnode.conf"; then
    fail "mmcblk root was accepted"
fi

# saved_entry wins over a newer file
boot="${tmp}/boot"
mkdir -p "${boot}/loader/entries" "${boot}/grub2"
cat > "${boot}/loader/entries/ostree-1-fedora.conf" <<'EOF'
options root=UUID=11111111-2222-3333-4444-555555555555 rw ostree=/ostree/boot.0/fedora/old/0
EOF
sleep 1
cat > "${boot}/loader/entries/ostree-2-fedora.conf" <<'EOF'
options root=UUID=11111111-2222-3333-4444-555555555555 rw ostree=/ostree/boot.0/fedora/new/0
EOF
printf 'saved_entry=ostree-1-fedora\n' > "${boot}/grub2/grubenv"
chosen=$(rpi5_default_bls "$boot")
[[ "$chosen" == *ostree-1-fedora.conf ]] || fail "saved_entry ignored: ${chosen}"

syncfat="${tmp}/syncfat"
mkdir -p "$syncfat"
write_kernel "${syncfat}/kernel_2712.img"
cp "${root}/build_files/rpi5/config.txt" "${syncfat}/config.txt"
RPI5_FAT_DIR="$syncfat" RPI5_BOOT_DIR="$boot" RPI5_CMDLINE_LIB="${root}/build_files/rpi5-cmdline.sh" \
    bash "${root}/build_files/rpi5-sync-cmdline.sh"
assert_contains "${syncfat}/cmdline.txt" "ostree=/ostree/boot.0/fedora/old/0"
if grep -q 'fedora/new' "${syncfat}/cmdline.txt"; then
    fail "sync followed the newer entry instead of saved_entry"
fi

RPI5_FAT_DIR="${tmp}/missing-fat" RPI5_BOOT_DIR="$boot" RPI5_CMDLINE_LIB="${root}/build_files/rpi5-cmdline.sh" \
    bash "${root}/build_files/rpi5-sync-cmdline.sh"

digest=$(grep -oE 'sha256:[0-9a-f]{64}' Containerfile | head -n 1)
[[ -n "$digest" ]] || fail "Containerfile has no digest pin"
assert_contains Containerfile.rpi5 "$digest"
assert_contains Containerfile.rpi5 "rpi5-prepare.sh"
if grep -q 'rpi5-prepare' Containerfile; then
    fail "UEFI Containerfile runs the Pi 5 prepare script"
fi
assert_contains build_files/rpi5-prepare.sh "kernel-rpi5"
assert_contains build_files/rpi5-prepare.sh "CONFIG_ARM64_16K_PAGES"
assert_contains build_files/rpi5-prepare.sh "CONFIG_EROFS_FS"
assert_contains build_files/rpi5/dracut-rpi5.conf "erofs"
assert_contains build_files/rpi5/config.txt "kernel=kernel_2712.img"
assert_contains build_files/rpi5/config.txt "dtoverlay=vc4-kms-v3d"
assert_contains Justfile "localhost/grokbotos-rpi5"
assert_contains Justfile "--rootfs ext4"
assert_contains Justfile "--rootfs=btrfs"
assert_contains Justfile "Containerfile.rpi5"
assert_contains disk_config/rpi5.toml 'mountpoint = "/"'
if grep -E '^[[:space:]]*kernel-rpi4( |\\|$)' build_files/rpi5-prepare.sh; then
    fail "prepare installs kernel-rpi4"
fi

echo "PASS test-rpi5-boot-layout.sh"
