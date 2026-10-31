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


# --- rpi5-sync-boot.sh: follow the default (highest version) BLS entry -------
sb="${tmp}/syncboot"
mkdir -p "${sb}/boot/loader/entries" "${sb}/fat/overlays" "${sb}/sysroot/ostree/boot.0/default/new" \
    "${sb}/sysroot/ostree/deploy/default/deploy"
for d in old.0 new.0; do
    p="${sb}/sysroot/ostree/deploy/default/deploy/${d}/usr/lib/grokbot/rpi5-boot"
    mkdir -p "${p}/overlays"
    write_kernel "${p}/kernel_2712.img"
    printf '%s\n' "$d" >> "${p}/kernel_2712.img"
    printf 'initrd-%s\n' "$d" > "${p}/initramfs_2712"
    printf 'dtb-%s\n' "$d" > "${p}/bcm2712-rpi-5-b.dtb"
    printf 'ovl-%s\n' "$d" > "${p}/overlays/vc4-kms-v3d.dtbo"
    printf 'kernel=kernel_2712.img\n# %s\n' "$d" > "${p}/config.txt"
    printf 'unfilled\n' > "${p}/cmdline.txt"
done
ln -s ../../../deploy/default/deploy/new.0 "${sb}/sysroot/ostree/boot.0/default/new/0"
mkdir -p "${sb}/sysroot/ostree/boot.0/default/old"
ln -s ../../../deploy/default/deploy/old.0 "${sb}/sysroot/ostree/boot.0/default/old/0"
cat > "${sb}/boot/loader/entries/ostree-2.conf" <<'EOS'
title new
version 2
options root=UUID=11111111-2222-3333-4444-555555555555 rw ostree=/ostree/boot.0/default/new/0
EOS
cat > "${sb}/boot/loader/entries/ostree-1.conf" <<'EOS'
title old
version 1
options root=UUID=11111111-2222-3333-4444-555555555555 rw ostree=/ostree/boot.0/default/old/0
EOS
touch -d '2020-01-01' "${sb}/boot/loader/entries/ostree-2.conf"   # mtime must not decide
old_payload="${sb}/sysroot/ostree/deploy/default/deploy/old.0/usr/lib/grokbot/rpi5-boot"
cp -r "${old_payload}/." "${sb}/fat/"
printf 'kernel=kernel_2712.img\n# local tweak\n' > "${sb}/fat/config.txt"
printf 'stale ostree=/ostree/boot.1/default/old/0\n' > "${sb}/fat/cmdline.txt"
sync_env=(RPI5_CMDLINE_LIB="${root}/build_files/rpi5-cmdline.sh" RPI5_BOOT_DIR="${sb}/boot"
    RPI5_FAT_DIR="${sb}/fat" RPI5_SYSROOT="${sb}/sysroot")
env "${sync_env[@]}" bash "${root}/build_files/rpi5-sync-boot.sh" 2>"${sb}/log" || fail "rpi5-sync-boot.sh failed: $(cat "${sb}/log")"
new_payload="${sb}/sysroot/ostree/deploy/default/deploy/new.0/usr/lib/grokbot/rpi5-boot"
cmp -s "${new_payload}/kernel_2712.img" "${sb}/fat/kernel_2712.img" || fail "sync-boot: kernel not from the default deployment"
cmp -s "${new_payload}/initramfs_2712" "${sb}/fat/initramfs_2712" || fail "sync-boot: initramfs not from the default deployment"
cmp -s "${new_payload}/bcm2712-rpi-5-b.dtb" "${sb}/fat/bcm2712-rpi-5-b.dtb" || fail "sync-boot: dtb not updated"
cmp -s "${new_payload}/overlays/vc4-kms-v3d.dtbo" "${sb}/fat/overlays/vc4-kms-v3d.dtbo" || fail "sync-boot: overlay not updated"
assert_contains "${sb}/fat/cmdline.txt" "ostree=/ostree/boot.0/default/new/0"
assert_contains "${sb}/fat/cmdline.txt" "rootwait"
assert_contains "${sb}/fat/config.txt" "# local tweak"
grep -q " 5 file(s) updated" "${sb}/log" || fail "sync-boot: expected 5 updated files: $(cat "${sb}/log")"
ls "${sb}/fat"/*.new >/dev/null 2>&1 && fail "sync-boot left .new files"
# Second run changes nothing.
env "${sync_env[@]}" bash "${root}/build_files/rpi5-sync-boot.sh" 2>"${sb}/log2" || fail "second sync failed"
assert_contains "${sb}/log2" "0 file(s) updated"
# No FAT, no entries: exit 0 without touching anything.
env RPI5_CMDLINE_LIB="${root}/build_files/rpi5-cmdline.sh" RPI5_BOOT_DIR="${sb}/none" RPI5_FAT_DIR="${sb}/fat" \
    RPI5_SYSROOT="${sb}/sysroot" bash "${root}/build_files/rpi5-sync-boot.sh" 2>/dev/null || fail "sync-boot failed without entries"
assert_contains "${sb}/fat/cmdline.txt" "ostree=/ostree/boot.0/default/new/0"
# Units: shutdown ordering and the boot-time path service use the new script.
assert_contains build_files/rpi5/grokbot-rpi5-boot-sync.service "Before=ostree-finalize-staged.service"
assert_contains build_files/rpi5/grokbot-rpi5-boot-sync.service "ExecStop=-/usr/bin/bash /usr/lib/grokbot/rpi5-sync-boot.sh"
assert_contains build_files/rpi5/grokbot-rpi5-cmdline.service "ExecStart=-/usr/bin/bash /usr/lib/grokbot/rpi5-sync-boot.sh"
assert_contains build_files/rpi5-prepare.sh "grokbot-rpi5-boot-sync.service"
assert_contains build_files/rpi5-prepare.sh "KERNEL_RPI5_EVR=6.18.57-1.rpi5.fc44"
echo "ok rpi5-sync-boot"
echo "PASS test-rpi5-boot-layout.sh"
