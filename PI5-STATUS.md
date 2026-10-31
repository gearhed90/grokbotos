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

## Fixes after first boot (dabb017)

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

## Next flash (branch feat/rpi5-next-flash)

다음 플래시: Nova 네이티브 앱이 기본 앱이 됩니다 (`/etc/grokbot/app.conf`의 `GROKBOT_MODE=native`). / Next flash: the Nova native app becomes the default app (`GROKBOT_MODE=native` in `/etc/grokbot/app.conf`).

잠금 화면은 이제 GTK4 + gtk4-layer-shell(ext-session-lock-v1) 키패드입니다. PIN은 grokbot 계정의 유닉스 비밀번호이며 PAM 서비스 `grokbot-lock`로 확인합니다. 키패드가 없으면 swaylock을 씁니다. / The lock screen is now a GTK4 + gtk4-layer-shell (ext-session-lock-v1) keypad. The PIN is the grokbot account's unix password, checked with the PAM service `grokbot-lock`. Without the keypad, swaylock is used.

화면 꺼짐 5분, 잠금 10분. Nova 창은 전체 화면이며 유휴 억제를 하지 않습니다. / Screen off after 5 minutes, lock after 10 minutes. The Nova window is fullscreen and does not inhibit idle.

xAI 키는 이미지에 들어 있지 않습니다. 관리자가 `sudo grokbot-set-xai-key`로 `/etc/grokbot/xai_key`(root:grokbot 0640)에 설정합니다. / The xAI key is not in the image. An admin sets it with `sudo grokbot-set-xai-key` into `/etc/grokbot/xai_key` (root:grokbot 0640).

이미지에는 기본 관리자 계정이 없습니다(2026-10-30 제거). 관리자 계정은 소유자가 직접 만듭니다. / The image ships no built-in admin account (removed 2026-10-30). The owner creates admin accounts.

RPM Fusion free의 libavcodec-freeworld로 브라우저 H.264/AAC 재생을 켭니다. 파일/노트/플레이어/시스템 앱은 기본 영어이며 버튼으로 한국어로 바꿀 수 있습니다. 글꼴은 Nunito(OFL)입니다. / libavcodec-freeworld from RPM Fusion free enables H.264/AAC in the browser. The files/notes/player/system apps default to English with a button to switch to Korean. The font is Nunito (OFL).

업데이트 출처는 `ghcr.io/gearhed90/grokbotos-rpi5:latest`로 설정되지만, 그 이미지가 올라가기 전까지는 오프라인 아카이브로 업데이트합니다: `sudo bootc switch --transport oci-archive /path/grokbotos-rpi5.oci.tar`. / The update source is set to `ghcr.io/gearhed90/grokbotos-rpi5:latest`, but until that image is pushed, update from the offline archive: `sudo bootc switch --transport oci-archive /path/grokbotos-rpi5.oci.tar`.

제자리 업데이트 / In-place updates: `bootc switch --transport oci-archive` or `bootc upgrade` stages the new deployment. At shutdown, after `ostree admin finalize-staged`, `grokbot-rpi5-boot-sync.service` runs `/usr/lib/grokbot/rpi5-sync-boot.sh`, which copies the new default deployment's kernel_2712.img, initramfs_2712, dtbs and overlays onto the FAT partition and rewrites cmdline.txt. `config.txt` on FAT is kept if it already exists. `grokbot-rpi5-cmdline.service` (boot, and on /boot/loader/entries changes such as `bootc rollback`) runs the same script. kernel-rpi5 is pinned in rpi5-prepare.sh (`KERNEL_RPI5_EVR`). The first switch from an image without this unit needs the sync run by hand before rebooting.

웨이크 워드("Nova")는 미뤘습니다. 사전 학습된 모델이 없고 빌드 때 pip 휠이 필요합니다. novad의 `wake_word_hook`은 남아 있고 기본은 꺼짐입니다. / The wake word ("Nova") is deferred. There is no pretrained model, and it needs pip wheels at build time. novad keeps `wake_word_hook`, off by default.

빌드: Alpha에서 `sudo /home/gearhed/grokbotos-rpi5/build-pi-image.sh`. 결과는 `/data/grokbotos-build/`에 저장됩니다. WiFi 연결 파일은 빌드 때 이전 이미지에서 복사하며 저장소에는 없습니다. / Build: on Alpha, `sudo /home/gearhed/grokbotos-rpi5/build-pi-image.sh`. Output goes to `/data/grokbotos-build/`. The WiFi connection file is copied from the old image at build time and is not in the repo.

테스트: `bash tests/run-tests.sh` (Nova 단위, 모의 xAI, 음성 테스트 포함). Pi 실기기와 GTK4 화면에서는 아직 테스트하지 않았습니다. / Tests: `bash tests/run-tests.sh` (includes Nova unit, mock-xAI and voice tests). Not yet tested on the Pi or on a real GTK4 screen.
