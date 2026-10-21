#!/bin/bash
# Boot a disk image in QEMU with a QMP and HMP socket for scripted testing.
# usage: tools/vm/vm.sh <disk.qcow2> [uefi|secboot|bios]
# Uses KVM if /dev/kvm is usable, otherwise TCG (GBVM_ACCEL=tcg to force).
set -euo pipefail
# shellcheck source=tools/vm/common.sh
source "$(dirname "$0")/common.sh"
disk=${1:?usage: vm.sh <disk.qcow2> [uefi|secboot|bios]}
mode=${2:-uefi}
fw=()
case $mode in
    uefi)
        [[ -f $GBVM_DIR/vars-uefi.fd ]] || cp "$GBVM_OVMF/OVMF_VARS_4M.fd" "$GBVM_DIR/vars-uefi.fd"
        fw=(-machine q35
            -drive "if=pflash,format=raw,readonly=on,file=$GBVM_OVMF/OVMF_CODE_4M.fd"
            -drive "if=pflash,format=raw,file=$GBVM_DIR/vars-uefi.fd") ;;
    secboot)
        cp "$GBVM_OVMF/OVMF_VARS_4M.ms.fd" "$GBVM_DIR/vars-secboot.fd"
        fw=(-machine "q35,smm=on" -global "driver=cfi.pflash01,property=secure,value=on"
            -drive "if=pflash,format=raw,unit=0,readonly=on,file=$GBVM_OVMF/OVMF_CODE_4M.secboot.fd"
            -drive "if=pflash,format=raw,unit=1,file=$GBVM_DIR/vars-secboot.fd") ;;
    bios) fw=(-machine q35) ;;
    *) echo "unknown mode: $mode" >&2; exit 2 ;;
esac
accel=${GBVM_ACCEL:-}
if [[ -z $accel ]]; then
    if [[ -w /dev/kvm ]]; then accel=kvm; else accel=tcg,thread=multi,tb-size=1024; fi
fi
exec qemu-system-x86_64 -accel "$accel" -m "$GBVM_MEM" -smp "$GBVM_SMP" -cpu max "${fw[@]}" \
    -drive "file=$disk,if=virtio,format=qcow2" \
    -device virtio-vga,xres=1280,yres=800 -display none \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -device qemu-xhci -device usb-kbd -device usb-tablet \
    -audiodev none,id=snd0 -device intel-hda -device hda-duplex,audiodev=snd0 \
    -serial "file:$GBVM_DIR/serial-$mode.log" \
    -monitor "unix:$GBVM_DIR/mon.sock,server,nowait" \
    -qmp "unix:$GBVM_DIR/qmp.sock,server,nowait"
