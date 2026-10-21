# 설치 / Install

> ✅ = VM에서 확인 / verified in a VM · ⚠️ = 미검증 / unverified. 설치할 디스크는 **전부 지워진다** / the target disk is **wiped**.

## 요구 사항 / Requirements
- x86_64 PC (x86_64-v2 이상, 32비트 불가 / no 32-bit), RAM 4 GB 이상 / or more, 디스크 / disk 30 GB 이상 / or more.
- UEFI ✅, UEFI + Secure Boot ✅, 레거시 BIOS / legacy BIOS ✅ (`--generic-image`로 설치했을 때 / when installed with `--generic-image`).
- Broadcom `wl` 무선 칩 미지원 / Broadcom `wl` Wi-Fi chips are not supported. NVIDIA는 nouveau만 지원 / NVIDIA uses nouveau only ⚠️.

## USB 만들기 / Write the USB stick ⚠️
설치 ISO는 아직 공개되지 않았다. / No public installer ISO yet.
- Fedora Media Writer → "Select .iso file" → Write
- `sudo dd if=grokbot.iso of=/dev/sdX bs=4M status=progress oflag=sync` (`sdX` 확인 / double-check)
- Ventoy: ISO를 USB에 복사 / copy the ISO onto the drive

## BIOS 설정과 부팅 키 / Firmware & boot keys
- Dell F12 · Lenovo F12/Novo · HP F9/Esc · ASUS F8/Esc · Acer F12 · MSI F11 · Samsung F10.
- SATA 모드는 AHCI로 둔다 (RST/RAID 모드에서는 디스크가 안 보일 수 있음) / Set SATA to AHCI (in RST/RAID mode the disk may not show up).
- Secure Boot는 켜둬도 된다 / Secure Boot can stay on ✅.

## 다른 리눅스에서 설치 / Install from a live Linux ✅
```sh
sudo podman run --rm --privileged --pid=host -v /dev:/dev -v /var/lib/containers:/var/lib/containers \
  --security-opt label=type:unconfined_t ghcr.io/head77x/oais:latest \
  bootc install to-disk --wipe --generic-image --filesystem xfs \
  --target-imgref ghcr.io/head77x/oais:latest /dev/sdX
```

## 문제 해결 / Troubleshooting
- "Booting from Hard Disk..."에서 멈춤 / Hangs at "Booting from Hard Disk..." → `--generic-image`로 다시 설치 / reinstall with `--generic-image`.
- 화면이 검게 나옴(NVIDIA) / Black screen (NVIDIA) → GRUB에서 `e`를 눌러 커널 인자에 `nomodeset` 추가 / press `e` in GRUB and add `nomodeset` to the kernel arguments.
