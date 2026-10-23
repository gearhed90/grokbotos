#!/bin/bash
# Helpers for the Raspberry Pi 5 FAT boot partition.
# Sourced by rpi5-prepare.sh, rpi5-finalize-disk.sh, rpi5-sync-cmdline.sh,
# and tests/test-rpi5-boot-layout.sh.

# True when the file has the ARM64 image magic "ARMd" at offset 0x38.
# kernel-rpi5's vmlinux is that Image (usually with an EFI stub MZ prefix).
rpi5_kernel_magic_ok() {
    local path="$1"
    local magic size
    [[ -f "$path" ]] || return 1
    size=$(stat -c %s -- "$path")
    ((size >= 60)) || return 1
    magic=$(od -An -t x1 -j 56 -N 4 -- "$path" 2>/dev/null | tr -d ' \n')
    [[ "$magic" == "41524d64" ]]
}

# First BLS options line. A directory is searched for loader/entries/*.conf
# and then *.conf.
rpi5_bls_options() {
    local src="$1"
    local conf="" candidate line
    if [[ -d "$src" ]]; then
        for candidate in "$src"/loader/entries/*.conf "$src"/*.conf "$src"/boot/loader/entries/*.conf; do
            if [[ -f "$candidate" ]]; then
                conf=$candidate
                break
            fi
        done
        if [[ -z "$conf" ]]; then
            echo "no BLS entry under ${src}" >&2
            return 1
        fi
    else
        conf=$src
    fi
    [[ -f "$conf" ]] || {
        echo "BLS entry not found: ${src}" >&2
        return 1
    }
    line=$(grep -E '^options[[:space:]]+' "$conf" | head -n 1 || true)
    if [[ -z "$line" ]]; then
        echo "BLS entry ${conf} has no options line" >&2
        return 1
    fi
    printf '%s\n' "${line#options }" | sed 's/^[[:space:]]*//'
}

# Boot entry to follow. grubenv saved_entry wins; otherwise the newest conf.
rpi5_default_bls() {
    local boot_dir="$1"
    local entries="${boot_dir}/loader/entries"
    local envfile saved conf newest="" newest_mtime=0 mtime
    [[ -d "$entries" ]] || return 1
    for envfile in "${boot_dir}/grub2/grubenv" "${boot_dir}/efi/grubenv" "${boot_dir}/grubenv"; do
        [[ -f "$envfile" ]] || continue
        saved=$(grep -a -E '^saved_entry=' "$envfile" | head -n 1 | cut -d= -f2- | tr -d '\0[:space:]' || true)
        if [[ -n "$saved" && -f "${entries}/${saved}.conf" ]]; then
            printf '%s\n' "${entries}/${saved}.conf"
            return 0
        fi
        if [[ -n "$saved" && -f "${entries}/${saved}" ]]; then
            printf '%s\n' "${entries}/${saved}"
            return 0
        fi
    done
    for conf in "${entries}"/*.conf; do
        [[ -f "$conf" ]] || continue
        mtime=$(stat -c %Y -- "$conf")
        if ((mtime >= newest_mtime)); then
            newest=$conf
            newest_mtime=$mtime
        fi
    done
    [[ -n "$newest" ]] || return 1
    printf '%s\n' "$newest"
}

# Linux cmdline for the Pi EEPROM, taken from a bootc BLS entry.
# Drops Pi 4 kernel paths. Refuses a missing root= and /dev/mmcblk*.
rpi5_cmdline_from_bls() {
    local src="$1"
    local options token joined
    local -a tokens=()
    local -a kept=()
    options=$(rpi5_bls_options "$src") || return 1
    if [[ "$options" == *BOOTC_CMDLINE_UNFILLED* ]]; then
        echo "refusing cmdline that still contains BOOTC_CMDLINE_UNFILLED" >&2
        return 1
    fi
    read -r -a tokens <<< "$options"
    for token in "${tokens[@]}"; do
        case "$token" in
            *kernel8.img* | kernel=* | /efi/*)
                continue
                ;;
        esac
        kept+=("$token")
    done
    if [[ ${#kept[@]} -eq 0 ]]; then
        echo "BLS options were empty after removing Pi 4 kernel paths" >&2
        return 1
    fi
    joined="${kept[*]}"
    if [[ "$joined" == *"/dev/mmcblk"* || "$joined" == *"/dev/nvme"* ]]; then
        echo "refusing a device-node root=; bootc must use root=UUID=" >&2
        return 1
    fi
    if [[ "$joined" != *"root="* ]]; then
        echo "BLS options have no root= argument; refusing /dev/mmcblk0p2" >&2
        return 1
    fi
    if [[ "$joined" != *"console=serial0,115200"* ]]; then
        joined="console=serial0,115200 ${joined}"
    fi
    if [[ "$joined" != *"console=tty1"* ]]; then
        joined="${joined} console=tty1"
    fi
    if [[ "$joined" != *"rootwait"* ]]; then
        joined="${joined} rootwait"
    fi
    printf '%s\n' "$joined"
}

# Copy the staged payload onto a FAT directory and rewrite cmdline.txt.
rpi5_install_boot() {
    local payload="$1"
    local fat="$2"
    local bls="$3"
    local cmdline entry name
    local nullglob_was=0 dotglob_was=0
    [[ -d "$payload" ]] || {
        echo "payload dir missing: ${payload}" >&2
        return 1
    }
    [[ -d "$fat" ]] || {
        echo "FAT dir missing: ${fat}" >&2
        return 1
    }
    [[ -f "${payload}/kernel_2712.img" ]] || {
        echo "payload has no kernel_2712.img" >&2
        return 1
    }
    [[ -f "${payload}/config.txt" ]] || {
        echo "payload has no config.txt" >&2
        return 1
    }
    if ! grep -q '^kernel=kernel_2712.img$' "${payload}/config.txt"; then
        echo "config.txt must set kernel=kernel_2712.img at the FAT root" >&2
        return 1
    fi
    if grep -E '^[^#]*kernel8\.img|^[^#]*kernel=/efi/' "${payload}/config.txt"; then
        echo "config.txt still points the EEPROM at a Linux path" >&2
        return 1
    fi
    cmdline=$(rpi5_cmdline_from_bls "$bls") || return 1
    shopt -q nullglob && nullglob_was=1
    shopt -q dotglob && dotglob_was=1
    shopt -s nullglob dotglob
    for entry in "${payload}"/*; do
        name=$(basename "$entry")
        [[ "$name" == "." || "$name" == ".." ]] && continue
        # The placeholder cmdline is rewritten from the BLS entry.
        [[ "$name" == "cmdline.txt" ]] && continue
        if [[ -d "$entry" ]]; then
            mkdir -p "${fat}/${name}"
            cp -a "${entry}/." "${fat}/${name}/"
        else
            cp -a "$entry" "${fat}/${name}"
        fi
    done
    [[ "$nullglob_was" -eq 1 ]] || shopt -u nullglob
    [[ "$dotglob_was" -eq 1 ]] || shopt -u dotglob
    printf '%s\n' "$cmdline" > "${fat}/cmdline.txt"
    [[ -f "${fat}/kernel_2712.img" ]] || return 1
    if grep -q 'BOOTC_CMDLINE_UNFILLED' "${fat}/cmdline.txt"; then
        echo "final cmdline.txt still contains BOOTC_CMDLINE_UNFILLED" >&2
        return 1
    fi
    if grep -q 'kernel8.img' "${fat}/cmdline.txt"; then
        echo "final cmdline.txt still points at kernel8.img" >&2
        return 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if [[ $# -lt 1 ]]; then
        echo "usage: rpi5-cmdline.sh bls-file-or-dir" >&2
        exit 2
    fi
    rpi5_cmdline_from_bls "$1"
fi
