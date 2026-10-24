#!/bin/bash
# Build the Raspberry Pi 5 SD-card image of Grok Bot OS on an x86_64 Linux
# host (Alpha-Station, Linux Mint 22 / Ubuntu 24.04). One command, as root:
#
#   sudo /home/gearhed/grokbotos-rpi5/build-pi-image.sh
#
# Takes no arguments and reads no environment overrides, so it can also be
# installed root-owned as /usr/local/sbin/grokbotos-build-pi (see PI5-STATUS.md).
# Steps: install podman + qemu-user-static if missing, build the arm64
# container (Containerfile.rpi5), make the raw ext4 disk with
# bootc-image-builder, fill the FAT boot partition (rpi5-finalize-disk.sh),
# copy the saved Wi-Fi network from the previous image, point updates at the
# registry ref below, then write .img, .img.xz and .sha256 into OUT.
# Never prints Wi-Fi or key contents.
set -euo pipefail
umask 022

REPO=/home/gearhed/grokbotos-rpi5
OUT=/data/grokbotos-build
OWNER=gearhed
IMAGE=localhost/grokbotos-rpi5:latest
NAME=grokbotos-rpi5
# Where `bootc upgrade` looks for new images. Nothing is published there yet:
# push the image (see PI5-STATUS.md "Updates") or `bootc switch` on the Pi.
UPDATE_REF=ghcr.io/gearhed90/grokbotos-rpi5:latest
# Saved Wi-Fi (NetworkManager keyfile) comes from the last working image.
WIFI_SRC=/home/gearhed/grokbotos-rpi5-image/grokbotos-rpi5-wifi.img.xz
# Pinned like grokbotos.env (not sourced, on purpose).
BIB_IMAGE="quay.io/centos-bootc/bootc-image-builder:latest@sha256:e8df8c535ffe40b418e44dd55abd2c11f65602468661b34e0ea98a532a8e577c"

log() { printf '\n== %s\n' "$*"; }
die() { echo "build-pi-image: $*" >&2; exit 1; }

(( $# == 0 )) || die "takes no arguments"
(( EUID == 0 )) || die "run with sudo"
[[ $(uname -m) == x86_64 || $(uname -m) == aarch64 ]] || die "unsupported host $(uname -m)"
[[ -f $REPO/Containerfile.rpi5 ]] || die "no repo at $REPO"
install -d -o "$OWNER" -g "$OWNER" -m 0755 "$OUT"
work=$(mktemp -d "$OUT/.work.XXXXXX")
mnt=$(mktemp -d)
loops=()
cleanup() {
    local m l
    for m in "$mnt"/new "$mnt"/old; do mountpoint -q "$m" && umount "$m" || true; done
    for l in "${loops[@]}"; do losetup -d "$l" 2>/dev/null || true; done
    rm -rf "$mnt" "$work"
}
trap cleanup EXIT
start=$(date +%s)

log "1/7 prerequisites"
need=()
command -v podman >/dev/null || need+=(podman)
if [[ $(uname -m) == x86_64 && ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
    need+=(qemu-user-static binfmt-support)
fi
command -v xz >/dev/null || need+=(xz-utils)
command -v losetup >/dev/null || need+=(util-linux)
if (( ${#need[@]} )); then
    command -v apt-get >/dev/null || die "install: ${need[*]}"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${need[@]}"
fi
if [[ $(uname -m) == x86_64 ]]; then
    [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]] || systemctl restart systemd-binfmt 2>/dev/null || true
    [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]] || die "aarch64 binfmt (qemu-user-static) is not registered"
    grep -q '^flags:.*F' /proc/sys/fs/binfmt_misc/qemu-aarch64 || die "qemu-aarch64 binfmt lacks the F flag (needed inside containers)"
fi
avail=$(df --output=avail -B1G "$OUT" | tail -1 | tr -d ' ')
(( avail >= 80 )) || die "need ~80 GB free in $OUT (have ${avail} GB)"
[[ -f $WIFI_SRC ]] || echo "warning: $WIFI_SRC missing; the image will have no saved Wi-Fi" >&2

log "2/7 container build (arm64, emulated; the longest step)"
podman build \
    --arch arm64 \
    --build-arg TARGETARCH=arm64 \
    --pull=newer \
    --tag "$IMAGE" \
    --file "$REPO/Containerfile.rpi5" \
    "$REPO"

log "3/7 raw disk (bootc-image-builder)"
install -d "$work/bib"
podman run --rm --privileged --pull=newer --net=host \
    --security-opt label=type:unconfined_t \
    -v "$REPO/disk_config/rpi5.toml:/config.toml:ro" \
    -v "$work/bib:/output" \
    -v /var/lib/containers/storage:/var/lib/containers/storage \
    "$BIB_IMAGE" \
    --type raw --use-librepo=True --rootfs ext4 --target-arch arm64 --local \
    "$IMAGE"
raw=$(find "$work/bib" -type f -name disk.raw -print -quit)
[[ -n $raw ]] || die "bootc-image-builder wrote no disk.raw"

log "4/7 Pi boot partition (rpi5-finalize-disk.sh)"
bash "$REPO/build_files/rpi5-finalize-disk.sh" "$raw"

log "5/7 Wi-Fi and update source"
root_part() {  # largest ext4 partition of a loop device
    lsblk -lnpbo NAME,FSTYPE,SIZE "$1" | awk '$2=="ext4"{print $3, $1}' | sort -n | tail -1 | cut -d' ' -f2
}
new_loop=$(losetup --find --show --partscan "$raw"); loops+=("$new_loop")
udevadm settle 2>/dev/null || sleep 2
mkdir -p "$mnt/new" "$mnt/old"
mount "$(root_part "$new_loop")" "$mnt/new"
deploy=$(find "$mnt/new/ostree/deploy" -mindepth 3 -maxdepth 3 -type d -path '*/ostree/deploy/*/deploy/*.0' -print -quit)
[[ -n $deploy ]] || die "no ostree deployment in the new disk"
origin="${deploy}.origin"
[[ -f $origin ]] || die "no origin file next to $deploy"
sed -i "s|^container-image-reference=.*|container-image-reference=ostree-unverified-registry:${UPDATE_REF}|" "$origin"
echo "updates: ostree-unverified-registry:${UPDATE_REF}"

if [[ -f $WIFI_SRC ]]; then
    old_raw="$work/old.img"
    xz -dc "$WIFI_SRC" >"$old_raw"
    old_loop=$(losetup --find --show --read-only --partscan "$old_raw"); loops+=("$old_loop")
    udevadm settle 2>/dev/null || sleep 2
    mount -o ro "$(root_part "$old_loop")" "$mnt/old"
    dest="$deploy/etc/NetworkManager/system-connections"
    install -d -m 0700 "$dest"
    n=0
    while IFS= read -r -d '' f; do
        install -m 0600 -o root -g root "$f" "$dest/$(basename "$f")"
        n=$(( n + 1 ))
    done < <(find "$mnt/old/ostree/deploy" "$mnt/old/etc" -path '*/etc/NetworkManager/system-connections/*.nmconnection' -type f -print0 2>/dev/null)
    umount "$mnt/old"
    losetup -d "$old_loop"
    rm -f "$old_raw"
    echo "Wi-Fi: copied $n saved network file(s) (contents not shown)"
fi
sync
umount "$mnt/new"
losetup -d "$new_loop"
loops=()

log "6/7 write $OUT/$NAME.img, .img.xz, .sha256"
mv -f "$raw" "$OUT/$NAME.img"
rm -f "$OUT/$NAME.img.xz"
xz -T0 -6 -k "$OUT/$NAME.img"
( cd "$OUT" && sha256sum "$NAME.img" "$NAME.img.xz" >"$NAME.sha256" )
chown "$OWNER:$OWNER" "$OUT/$NAME.img" "$OUT/$NAME.img.xz" "$OUT/$NAME.sha256"

log "7/7 offline update archive (bootc switch --transport oci-archive)"
rm -f "$OUT/$NAME.oci.tar"
podman save --format oci-archive -o "$OUT/$NAME.oci.tar" "$IMAGE"
chown "$OWNER:$OWNER" "$OUT/$NAME.oci.tar"

mins=$(( ($(date +%s) - start) / 60 ))
cat <<MSG

Done in ${mins} min.
  $OUT/$NAME.img       ($(du -h "$OUT/$NAME.img" | cut -f1))
  $OUT/$NAME.img.xz    ($(du -h "$OUT/$NAME.img.xz" | cut -f1))
  $OUT/$NAME.sha256
  $OUT/$NAME.oci.tar   (offline update)

Flash: first check which disk is the SD card (removable, ~the card's size):
  lsblk -o NAME,SIZE,RM,TRAN,MODEL
Then (only if it is still /dev/sdc):
  sudo /usr/local/sbin/grokbotos-flash-card $OUT/$NAME.img /dev/sdc
or:
  sudo dd if=$OUT/$NAME.img of=/dev/sdc bs=4M conv=fsync status=progress
MSG
