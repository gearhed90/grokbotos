#!/bin/bash
# After bootc-image-builder, copy the staged Pi 5 payload onto the FAT ESP
# and fill cmdline.txt from the bootc BLS entry.
#
# Directory mode (no root), used by tests:
#   RPI5_FAT_DIR=... RPI5_BOOT_PAYLOAD=... RPI5_BLS=... rpi5-finalize-disk.sh
#
# Image mode:
#   sudo rpi5-finalize-disk.sh output/raw/disk.raw
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC1091
source "${root}/build_files/rpi5-cmdline.sh"

usage() {
    echo "usage: rpi5-finalize-disk.sh [disk.raw]" >&2
    echo "  directory mode: set RPI5_FAT_DIR, RPI5_BOOT_PAYLOAD, RPI5_BLS" >&2
    echo "  image mode: pass the raw disk (needs root and losetup)" >&2
}

rpi5_finalize_dirs() {
    rpi5_install_boot "${RPI5_BOOT_PAYLOAD}" "${RPI5_FAT_DIR}" "${RPI5_BLS}"
}

rpi5_find_one() {
    local rootmnt="$1"
    local expr="$2"
    find "$rootmnt" -path "$expr" -print -quit 2>/dev/null || true
}

rpi5_finalize_image() {
    local image="$1"
    local work loop node fstype mountpoint
    local fat_mnt="" payload="" bls=""
    local -a mounts=()
    local -a nodes=()
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "Mounting ${image} needs root. Re-run with sudo, or set RPI5_FAT_DIR, RPI5_BOOT_PAYLOAD and RPI5_BLS." >&2
        return 1
    fi
    command -v losetup >/dev/null 2>&1 || {
        echo "losetup is not installed; the raw image was not modified." >&2
        return 1
    }
    [[ -f "$image" ]] || {
        echo "not a file: ${image}" >&2
        return 1
    }
    work=$(mktemp -d)
    loop=""
    # shellcheck disable=SC2317
    cleanup() {
        local i
        for ((i = ${#mounts[@]} - 1; i >= 0; i--)); do
            umount "${mounts[i]}" 2>/dev/null || true
        done
        if [[ -n "$loop" ]]; then
            losetup -d "$loop" 2>/dev/null || true
        fi
        rm -rf "$work"
    }
    trap cleanup RETURN
    loop=$(losetup --find --show --partscan "$image")
    if command -v partx >/dev/null 2>&1; then
        partx -u "$loop" || true
    fi
    if command -v udevadm >/dev/null 2>&1; then
        udevadm settle || true
    else
        sleep 1
    fi
    if command -v lsblk >/dev/null 2>&1; then
        while read -r node fstype; do
            if [[ "$fstype" == "part" ]]; then
                nodes+=("$node")
            fi
        done < <(lsblk -lnpo NAME,TYPE "$loop")
    fi
    if [[ ${#nodes[@]} -eq 0 ]]; then
        shopt -s nullglob
        nodes=("${loop}"p* "${loop}"[0-9])
        shopt -u nullglob
    fi
    local idx=0
    for node in "${nodes[@]}"; do
        [[ -b "$node" ]] || continue
        fstype=$(blkid -o value -s TYPE "$node" 2>/dev/null || true)
        if [[ "$fstype" == "swap" || "$fstype" == "LVM2_member" ]]; then
            continue
        fi
        mountpoint="${work}/p${idx}"
        mkdir -p "$mountpoint"
        if mount -o rw "$node" "$mountpoint"; then
            mounts+=("$mountpoint")
            if [[ "$fstype" == "vfat" ]]; then
                if [[ -z "$fat_mnt" || -d "${mountpoint}/EFI" ]]; then
                    fat_mnt=$mountpoint
                fi
            fi
            idx=$((idx + 1))
        fi
    done
    payload=$(rpi5_find_one "$work" '*/usr/lib/grokbot/rpi5-boot/kernel_2712.img')
    bls=$(rpi5_find_one "$work" '*/loader/entries/*.conf')
    if [[ -z "$payload" ]]; then
        echo "disk has no /usr/lib/grokbot/rpi5-boot (not built from Containerfile.rpi5?)" >&2
        return 1
    fi
    if [[ -z "$bls" ]]; then
        echo "disk has no BLS loader/entries; cannot fill cmdline.txt" >&2
        return 1
    fi
    if [[ -z "$fat_mnt" ]]; then
        echo "no FAT partition to write kernel_2712.img onto" >&2
        return 1
    fi
    payload=$(dirname "$payload")
    bls=$(dirname "$bls")
    echo "payload ${payload}"
    echo "bls ${bls}"
    echo "fat ${fat_mnt}"
    rpi5_install_boot "$payload" "$fat_mnt" "$bls"
}

if [[ -n "${RPI5_FAT_DIR:-}${RPI5_BOOT_PAYLOAD:-}${RPI5_BLS:-}" ]]; then
    if [[ -z "${RPI5_FAT_DIR:-}" || -z "${RPI5_BOOT_PAYLOAD:-}" || -z "${RPI5_BLS:-}" ]]; then
        echo "directory mode needs RPI5_FAT_DIR, RPI5_BOOT_PAYLOAD and RPI5_BLS" >&2
        exit 2
    fi
    rpi5_finalize_dirs
    exit 0
fi

if [[ $# -eq 1 ]]; then
    rpi5_finalize_image "$1"
    exit 0
fi

usage
exit 2
