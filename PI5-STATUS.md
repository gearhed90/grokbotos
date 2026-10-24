# Raspberry Pi 5 status

Pi 5 실기에서 이 브랜치로 만든 이미지가 끝까지 부팅했다. 남은 일은 아래에 적는다.

Checked 2026-10-23 on a real Raspberry Pi 5 with a Raspberry Pi Touch Display 2 (7-inch, DSI port 1), USB keyboard and serial console.

## What booted

`just build-rpi5-raw` on a Linux machine with privileged podman produced `output/raw/disk.raw`. It was written to microSD and booted on a Pi 5 with serial on the UART (`ttyAMA10`, 115200).

- The EEPROM read `config.txt` from the FAT root and loaded `kernel_2712.img` and `initramfs_2712`. No EEPROM boot-order or tryboot setting was changed.
- Kernel `6.18.57-1.rpi5.fc44.aarch64` (16K pages) booted with Fedora aarch64 userspace.
- `ostree-prepare-root` mounted the composefs/EROFS root. The ostree deployment came up read-only as designed.
- The kiosk sway session and the Grok Bot app started. Screen-lock PIN setup and sign-in were reached.
- Onboard Wi-Fi (CYW43455, `brcmfmac`) connected through a NetworkManager keyfile using the stock Fedora firmware. No extra firmware file was needed.
- USB keyboard (RPI Wired Keyboard 4 behind a USB2.0 hub) worked.

Real `cmdline.txt` as seen in `/proc/cmdline` (firmware prefix first, then ours):

```
... console=ttyAMA10,115200 root=UUID=<rootfs> rw boot=UUID=<boot> console=tty0 console=ttyS0 ostree=/ostree/boot.1/default/<checksum>/0 console=tty1 rootwait
```

## Fixes in dfbe8e3

- `TARGETARCH` build arg passed into `Containerfile.rpi5` so the arm64 build takes the right path.
- `vmlinux` is copied to `vmlinuz` in the module dir, which bootc and dracut expect.
- BLS lookup uses a `loader*` glob (`loader` or `loader.1`) instead of one fixed directory.
- FAT staging copies with `cp -rL`, since FAT cannot hold symlinks.

## Fixes after first boot (this change, not yet committed)

These were first made by hand on the card, then moved into the repo:

- `build_files/rpi5/config.txt`: `dtoverlay=vc4-kms-dsi-ili9881-7inch` after `dtoverlay=vc4-kms-v3d`. Without it the Touch Display 2 stayed blank. 5-inch panel: `vc4-kms-dsi-ili9881-5inch`. Port 0: append `,dsi0`.
- `build_files/rpi5/sway-rpi5-dsi.conf`, installed by `rpi5-prepare.sh` as `/etc/sway/grokbot.d/50-rpi5-dsi.conf`: the panel is portrait and sway names it `DSI-2`. It sets `transform 90` and `input type:touch map_to_output DSI-2`. Mapping touch to `DSI-1` killed touch.
- Dock off by default on the Pi image (`dock = off` in `/etc/grokbot/desktop.conf`), so the Pi shows the wallpaper with Grok Bot in front.

## Open questions now answered

- 16K-page kernel with Fedora 64K-aligned userspace: works.
- `ostree-prepare-root` with EROFS (zstd only): works.
- Wi-Fi with stock `bcm434xx-firmware`: works.
- EEPROM: FAT-root `kernel_2712.img` boots with no boot-order change.
- Real BLS options: `root=UUID=... rw boot=UUID=... ostree=/ostree/boot.1/default/<sum>/0` (above). Finalize filled them correctly.
- The kernel image copy (`vmlinux` to `kernel_2712.img` / `vmlinuz`) works.

## What remains

- `grokbot-rpi5-cmdline.service` / `.path` has not been tested against `bootc upgrade` or `bootc rollback`. A rollback that leaves `cmdline.txt` pointing at the old deployment is the main risk.
- `bootc container lint` result after `/boot` is cleared should be recorded from a clean build.
- Display rotation is a fixed `transform 90`. Settings > Display does not expose rotation, and saving display settings there may override it.
- Built-in web apps start in Korean; each has a language switch.
- Audio, camera, NVMe, HDMI alongside DSI, and suspend have not been tested.
- QEMU still cannot stand in for the EEPROM, the SD controller, vc4 or brcmfmac. Test on hardware.

## What was not changed

`.github/workflows/` was not modified. Image names stay `grokbotos` and `grokbotos-arm64`. The Pi recipe tags `localhost/grokbotos-rpi5`.
