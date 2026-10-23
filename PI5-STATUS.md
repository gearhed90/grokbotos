# Raspberry Pi 5 status

Pi 5용 디스크 이미지는 아직 없다. 부팅 파일 배치만 저장소에 들어 있다. 실기 없이는 더 진행하지 않는다.

Checked 2026-10-23. Nothing here is safe to flash. There is no SD card image.

## What successfully built

Nothing you can boot. There is no container image and no raw disk.

What is in the tree:

- A separate Pi 5 image, `Containerfile.rpi5`, on top of the current Fedora bootc pin in `Containerfile` (`sha256:03808453feb5369ed6b074421117b56734f3a6dff8e25d9e0ddff0e48e4d6d2e`). The generic UEFI image stays `grokbotos` / `grokbotos-arm64`. The Pi recipe tags `localhost/grokbotos-rpi5`.
- EEPROM boot files: `kernel=kernel_2712.img` at the FAT root, not `/efi/kernel8.img`. The Pi disk is ext4. The desktop disk stays btrfs.
- `bash tests/test-rpi5-boot-layout.sh` checks that a Fedora-style `/efi/kernel8.img` command line is rewritten to the bootc `root=UUID=` plus `ostree=` options, and that `root=/dev/mmcblk0p2` is refused.

An earlier look at the dwrobel COPR RPMs (not a rebuild) found kernel-rpi5 6.18.57-1.rpi5.fc43 with `CONFIG_ARM64_16K_PAGES=y` and `CONFIG_EROFS_FS=m`. EROFS zip was zstd only. The kernel file started with MZ and had ARM64 magic `ARMd` at offset 0x38. DTBs included `bcm2712-rpi-5-b.dtb`. Overlays included `vc4-kms-v3d.dtbo`. `bcm283x-firmware` 20260911-1.ae2a7dc.fc43 had `bootcode.bin` and `start*.elf`, and no `start5.elf`.

## What failed

The raw disk was not built.

- This machine has no working `podman`. `apt-get install podman` stops on systemd:

```
Failed to copy permissions from /etc/gshadow to /etc/.#gshadowGsTIQd: Invalid argument
dpkg: error processing package systemd (--configure):
 installed systemd package post-installation script subprocess returned error exit status 1
E: Sub-process /usr/bin/dpkg returned an error code (1)
```

Unpacking the debs by hand was abandoned after `dpkg-deb` itself stopped executing (`cannot execute: required file not found`) and the checkout disappeared from disk. The layout was rewritten onto current `main` after that. Do not treat a half-installed podman on this machine as usable.

- QEMU 7.2.22 has no `raspi4` or `raspi5` machine (only raspi0, raspi1ap, raspi2b, raspi3ap, raspi3b). Booting the extracted 16K kernel with `-cpu cortex-a72` and AAVMF printed `EFI stub: ERROR: This 16 KB granular kernel is not supported by your CPU`. With `-cpu max` it printed `Booting Linux on physical CPU 0x0000000000` and `Linux version 6.18.57-1.rpi5.fc43.aarch64`, then `Unable to handle kernel NULL pointer dereference at virtual address 0000000000001c08` in `nr_free_zone_pages` during `start_kernel`, plus `Failed to find device node for boot cpu`. That is a virt machine, not a Pi 5. It was not patched.

## What we learned about the boot layout

The Pi 5 mask ROM loads the bootloader from the SPI EEPROM. It does not run `bootcode.bin` off the SD card. The EEPROM reads `config.txt` from the first FAT partition, then the kernel, DTB and initramfs. It does not start Linux through `start.elf`.

Pi 5's kernel is `kernel_2712.img` (16K pages). If that file is missing, firmware falls back to `kernel8.img` (4K). Fedora's kernel-rpi4 package publishes `/boot/efi/kernel8.img`. mrguitar/fedora-rpi5-bootc installs that Pi 4 kernel and says the image does not boot yet. This layout does not follow it. ondrejbudai/fedora-bootc-raspi is Pi 4 U-Boot. This layout does not use U-Boot.

`config.txt` sets `kernel=kernel_2712.img` and `initramfs initramfs_2712 followkernel`. Display is `dtoverlay=vc4-kms-v3d`. Wi-Fi is the onboard CYW43455 (`brcmfmac`) described by `bcm2712-rpi-5-b.dtb`. There is no overlay that turns Wi-Fi on.

bootc writes a BLS entry (`root=UUID=... ostree=/ostree/...`) and owns `/boot`. The Pi never reads that entry. `rpi5-prepare.sh` stages the FAT files under `/usr/lib/grokbot/rpi5-boot` and then empties `/boot`. `rpi5-finalize-disk.sh` copies them onto the FAT partition and rewrites `cmdline.txt` from the BLS options. It refuses `BOOTC_CMDLINE_UNFILLED` and `root=/dev/mmcblk0p2`. EROFS is a module, so dracut is told to include `erofs` and `overlay`. `grokbot-rpi5-cmdline.service` rewrites `cmdline.txt` when the boot entry changes. That unit has not run on a board.

## The single next step

On the local Linux machine that has privileged podman (and qemu-user-static if it is not arm64), clone this branch and run `just build-rpi5-raw`. Write the raw image it prints (`output/raw/disk.raw`) to a microSD card. Boot a Raspberry Pi 5 with serial on the UART at 115200 and save the console from power-on through `ostree-prepare-root`. There is no image here to flash.

## Open questions

- Does `bcm434xx-firmware` ship `brcmfmac43455-sdio.raspberrypi,5-model-b.txt`, or only a generic `brcmfmac43455-sdio.txt`? Wi-Fi may fail until that filename is confirmed on the board.
- `bootc container lint` was not run after `/boot` is cleared.
- The exact BLS `options` line from a real bootc-image-builder disk is unknown. Finalize will not invent `root=`.
- The EEPROM may need a boot-order or tryboot setting beyond FAT-root `kernel_2712.img`.
- Fedora aarch64 userspace is 64K-ELF-aligned, so a 16K kernel should be allowed. That was not proven on a board.
- kernel-rpi5's scriptlet copies `vmlinux` to `/boot/efi/kernel_2712.img`. If `/boot/efi` is missing during the build, prepare falls back to `vmlinux`. Not run.
- This kernel had `CONFIG_EROFS_FS_ZIP_ZSTD` only. lzma and deflate were off. If composefs uses another compressor, `ostree-prepare-root` fails.
- The cmdline sync unit has not been tested against `bootc upgrade` or `bootc rollback`.
- QEMU cannot stand in for the EEPROM, the SD controller, vc4 or brcmfmac.

## What was not changed

`.github/workflows/` was not modified. Image names stay `grokbotos` and `grokbotos-arm64`.
