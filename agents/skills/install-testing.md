# Skill: install and bootloader testing

The user-facing steps are in [`manual/install.md`](../../manual/install.md).

## Install to a blank disk in a VM

Boot a helper VM (`vm-testing.md`) with a second blank disk (30 GB), load the image into podman, then run:

```bash
sudo podman run --rm --privileged --pid=host -v /dev:/dev -v /var/lib/containers:/var/lib/containers \
  --security-opt label=type:unconfined_t localhost/grokbotos:latest \
  bootc install to-disk --wipe --generic-image --filesystem xfs \
  --target-imgref ghcr.io/head77x/grokbotos:latest /dev/vdb
```

- `--generic-image` installs both the UEFI and BIOS bootloaders. Without it, an install from a UEFI-booted host does **not** boot on BIOS: SeaBIOS hangs at "Booting from Hard Disk..." (verified 2026-10-21).
- `--target-imgref` makes `bootc upgrade` pull from GHCR instead of `localhost`.
- Expected partitions: BIOS-BOOT 1 MiB, EFI-SYSTEM 512 MiB, root XFS.

## Boot the installed disk in each mode

`tools/vm/vm.sh target.qcow2 uefi|secboot|bios`. Take screenshots until the Grok Bot sign-in screen appears. Then check:

- `mokutil --sb-state` or the SecureBoot efivar (secboot mode)
- `getenforce` gives `Enforcing`
- `systemctl status bootloader-update.service`
- `bootc status`: the image ref must be the GHCR ref, not `localhost`

## Not yet covered

- ISO / Anaconda install. bootc-image-builder `--type anaconda-iso` needs a host kernel with vfat.
- Rollback entries. They appear only after the first `bootc upgrade`.
- Real hardware: Wi-Fi association, NVIDIA, suspend.
