#!/bin/bash
# Rewrite the Pi 5 FAT cmdline.txt from the default bootc BLS entry.
# The EEPROM does not read /boot/loader/entries. Exit 0 when there is
# nothing to do so a missed sync does not block boot.
set -euo pipefail

if [[ -n "${RPI5_CMDLINE_LIB:-}" ]]; then
    # shellcheck disable=SC1090
    source "$RPI5_CMDLINE_LIB"
else
    # shellcheck disable=SC1091
    source /usr/lib/grokbot/rpi5-cmdline.sh
fi

boot_dir=${RPI5_BOOT_DIR:-/boot}

rpi5_find_fat_mount() {
    local mnt fstype
    if [[ -n "${RPI5_FAT_DIR:-}" ]]; then
        if [[ -d "${RPI5_FAT_DIR}" ]]; then
            printf '%s\n' "${RPI5_FAT_DIR}"
            return 0
        fi
        return 1
    fi
    while read -r mnt fstype; do
        if [[ "$fstype" == vfat && -f "${mnt}/kernel_2712.img" ]]; then
            printf '%s\n' "$mnt"
            return 0
        fi
    done < <(findmnt -n -t vfat -o TARGET,FSTYPE 2>/dev/null || true)
    for mnt in /boot/efi /boot; do
        if [[ -f "${mnt}/config.txt" && -f "${mnt}/kernel_2712.img" ]]; then
            printf '%s\n' "$mnt"
            return 0
        fi
    done
    return 1
}

fat=""
bls=""
if ! fat=$(rpi5_find_fat_mount); then
    echo "rpi5-sync: no FAT boot partition with kernel_2712.img; leaving cmdline.txt alone" >&2
    exit 0
fi
if ! bls=$(rpi5_default_bls "$boot_dir"); then
    echo "rpi5-sync: no BLS entry under ${boot_dir}; keeping the existing cmdline.txt" >&2
    exit 0
fi
cmdline=$(rpi5_cmdline_from_bls "$bls")
tmp=$(mktemp)
printf '%s\n' "$cmdline" > "$tmp"
cp -f "$tmp" "${fat}/cmdline.txt"
rm -f "$tmp"
echo "rpi5-sync: wrote ${fat}/cmdline.txt from ${bls}" >&2
