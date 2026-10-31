#!/bin/bash
# Make the Pi 5 FAT boot partition match the default bootc deployment.
#
# The EEPROM reads kernel_2712.img, initramfs_2712, the dtbs, overlays/ and
# cmdline.txt from the FAT partition and never looks at /boot/loader, so after
# `bootc upgrade`, `bootc switch` or `bootc rollback` those files must be
# refreshed from the deployment that ostree made the default. This script:
#   1. picks the default BLS entry (ostree numbers entries so the highest
#      "version" is deployment index 0, the next boot),
#   2. follows its ostree= path to the deployment and copies that
#      deployment's /usr/lib/grokbot/rpi5-boot payload onto FAT (only files
#      that differ; each file is written to a temp name and renamed),
#   3. rewrites cmdline.txt from the same BLS entry.
# config.txt is only installed when FAT has none, so local firmware tweaks
# survive; a difference is reported.
#
# Run by grokbot-rpi5-boot-sync.service at shutdown (after
# ostree-finalize-staged writes the new entries) and by
# grokbot-rpi5-cmdline.service at boot and when /boot/loader/entries changes.
# Exits 0 when there is nothing it can safely do, so boot and shutdown never
# block on it.
#
# Test overrides: RPI5_CMDLINE_LIB, RPI5_BOOT_DIR, RPI5_FAT_DIR, RPI5_SYSROOT.
set -euo pipefail

if [[ -n "${RPI5_CMDLINE_LIB:-}" ]]; then
    # shellcheck disable=SC1090
    source "$RPI5_CMDLINE_LIB"
else
    # shellcheck disable=SC1091
    source /usr/lib/grokbot/rpi5-cmdline.sh
fi

boot_dir=${RPI5_BOOT_DIR:-/boot}
sysroot=${RPI5_SYSROOT:-/sysroot}

log() { echo "rpi5-sync-boot: $*" >&2; }

find_fat() {
    local mnt fstype
    if [[ -n "${RPI5_FAT_DIR:-}" ]]; then
        [[ -d "${RPI5_FAT_DIR}" ]] && { printf '%s\n' "${RPI5_FAT_DIR}"; return 0; }
        return 1
    fi
    while read -r mnt fstype; do
        if [[ "$fstype" == vfat && -f "${mnt}/kernel_2712.img" ]]; then
            printf '%s\n' "$mnt"
            return 0
        fi
    done < <(findmnt -n -t vfat -o TARGET,FSTYPE 2>/dev/null || true)
    return 1
}

# Default entry: highest numeric "version" among loader/entries/*.conf.
default_bls() {
    local entries="${boot_dir}/loader/entries" conf v best="" best_v=-1
    [[ -d "$entries" ]] || return 1
    for conf in "$entries"/*.conf; do
        [[ -f "$conf" ]] || continue
        v=$(awk '$1=="version"{print $2; exit}' "$conf")
        [[ "$v" =~ ^[0-9]+$ ]] || continue
        if (( v > best_v )); then
            best=$conf
            best_v=$v
        fi
    done
    if [[ -z "$best" ]]; then
        # No numbered entries: fall back to the shared helper.
        rpi5_default_bls "$boot_dir"
        return
    fi
    printf '%s\n' "$best"
}

# Deployment directory named by the entry's ostree= argument.
deployment_of() {
    local opts arg path
    opts=$(rpi5_bls_options "$1") || return 1
    for arg in $opts; do
        case "$arg" in ostree=*) path=${arg#ostree=} ;; esac
    done
    [[ -n "${path:-}" ]] || return 1
    readlink -e -- "${sysroot}${path}"
}

# Copy src to dst only when the bytes differ; temp name + rename.
put() {
    local src="$1" dst="$2"
    if [[ -f "$dst" ]] && cmp -s -- "$src" "$dst"; then
        return 0
    fi
    mkdir -p -- "$(dirname -- "$dst")"
    cp -fL -- "$src" "${dst}.new"
    sync -f "${dst}.new" 2>/dev/null || sync
    mv -f -- "${dst}.new" "$dst"
    changed=$((changed + 1))
}

fat=""
if ! fat=$(find_fat); then
    log "no FAT partition with kernel_2712.img; nothing changed"
    exit 0
fi
bls=""
if ! bls=$(default_bls); then
    log "no BLS entry under ${boot_dir}/loader/entries; nothing changed"
    exit 0
fi
cmdline=""
if ! cmdline=$(rpi5_cmdline_from_bls "$bls"); then
    log "could not build a cmdline from ${bls}; nothing changed"
    exit 0
fi

changed=0
deploy=""
if deploy=$(deployment_of "$bls") && [[ -f "${deploy}/usr/lib/grokbot/rpi5-boot/kernel_2712.img" ]]; then
    payload="${deploy}/usr/lib/grokbot/rpi5-boot"
    if ! rpi5_kernel_magic_ok "${payload}/kernel_2712.img"; then
        log "${payload}/kernel_2712.img is not an arm64 kernel; nothing changed"
        exit 0
    fi
    # Kernel and initramfs last, so a cut-off copy leaves the old pair together.
    while IFS= read -r -d '' f; do
        rel=${f#"${payload}/"}
        case "$rel" in
            cmdline.txt | kernel_2712.img | initramfs_2712) continue ;;
            config.txt)
                if [[ ! -f "${fat}/config.txt" ]]; then
                    put "$f" "${fat}/config.txt"
                elif ! cmp -s -- "$f" "${fat}/config.txt"; then
                    log "config.txt on FAT differs from the image; kept the FAT copy"
                fi
                continue
                ;;
        esac
        put "$f" "${fat}/${rel}"
    done < <(find "$payload" -type f -print0)
    [[ -f "${payload}/initramfs_2712" ]] && put "${payload}/initramfs_2712" "${fat}/initramfs_2712"
    put "${payload}/kernel_2712.img" "${fat}/kernel_2712.img"
else
    log "default deployment has no rpi5-boot payload; only cmdline.txt is updated"
fi

tmp="${fat}/cmdline.txt.new"
printf '%s\n' "$cmdline" > "$tmp"
if [[ -f "${fat}/cmdline.txt" ]] && cmp -s -- "$tmp" "${fat}/cmdline.txt"; then
    rm -f -- "$tmp"
else
    sync -f "$tmp" 2>/dev/null || sync
    mv -f -- "$tmp" "${fat}/cmdline.txt"
    changed=$((changed + 1))
fi
sync
log "default entry $(basename "$bls") -> ${deploy:-unknown deployment}; ${changed} file(s) updated on ${fat}"
