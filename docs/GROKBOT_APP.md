# Grok Bot 앱을 이미지에 넣는 방법

런타임 진입점은 항상 `/usr/local/bin/grokbot-launch`다. sway는 이 프로그램만 실행한다. 무엇을 실행할지는 이미지 빌드 때 `/etc/grokbot/app.conf`에 적힌다. 그 파일을 쓰는 프로그램은 `build_files/install-grokbot-app.sh` 하나다.

## 지금 상태

**기본 빌드는 Grok Bot 0.71.2 RPM을 넣는다.** amd64와 arm64 둘 다다. 플레이스홀더는 `GROKBOT_DISABLE_BUNDLED_APP=1`일 때만 남는다.

빌드가 고르는 파일은 아키텍처로 정해진다. `GROKBOT_TARGET_ARCH`가 있으면 그것을 쓰고, 없으면 이미지 빌드의 `TARGETARCH`, 그것도 없으면 `uname -m`이다. `amd64`/`x86_64`와 `arm64`/`aarch64`만 받는다. 다른 아키텍처는 빌드가 실패한다.

| 아키텍처 | RPM | sha256 | 크기 |
|---|---|---|---|
| x86_64 | `https://downloads.cursor.com/grokbot/stable/92808c0ad869b2e3725dbc3b8fa2fcc991687502/linux/x64/grok-bot-0.71.2-1.x86_64.rpm` | `ba68a9332675238deb3102dfcdab6d6e7978fa2aa281df5bbf11cbb61a19418a` | 92776633 |
| aarch64 | `https://downloads.cursor.com/grokbot/stable/92808c0ad869b2e3725dbc3b8fa2fcc991687502/linux/arm64/grok-bot-0.71.2-1.aarch64.rpm` | `9ff82fb7468ce08509e9a67945e96bc72fa2fb35283dc6132060e90ddd5da0be` | 87733289 |

이 개발 환경에서 두 파일을 받아 sha256이 위 값과 같은지 확인했다. `dnf5 install`과 부팅은 하지 않았다. 체크섬이 다르면 이미지 빌드는 실패한다. 조용히 플레이스홀더로 넘어가지 않는다.

`just build`는 환경 변수 `GROKBOT_TARGET_ARCH`를 `--build-arg`로 넘긴다. GitHub Actions `build.yml`은 매트릭스의 `amd64` / `arm64`를 그 변수로 넣는다.

### 쓰지 않는 latest 주소

아래 주소는 지금 빌드가 받는 그 버전으로 리다이렉트된다. 빌드는 이 주소를 쓰지 않는다. 다음 버전으로 넘어가면 리다이렉트 대상이 바뀌므로, 올릴 때는 위 고정 URL과 sha256을 같이 바꾼다.

| 종류 | 주소 |
|---|---|
| rpm x64 | `https://api2.cursor.sh/updates/download/stable/linux-x64/grok-bot-cc18e4e726507b90` |
| rpm arm64 | `https://api2.cursor.sh/updates/download/stable/linux-arm64/grok-bot-489eca1c3d454930` |
| deb x64 | `https://api2.cursor.sh/updates/download/stable/linux-x64/grok-bot-fb0a830618be0c54` |
| deb arm64 | `https://api2.cursor.sh/updates/download/stable/linux-arm64/grok-bot-922bf0a2bf7ebaa3` |
| AppImage x64 | `https://api2.cursor.sh/updates/download/stable/linux-x64/grok-bot-6f47c900083d6a0c` |
| AppImage arm64 | `https://api2.cursor.sh/updates/download/stable/linux-arm64/grok-bot-8719c297a3a85a27` |

이미지는 Fedora bootc라 deb가 아니라 RPM을 쓴다.

## 설치가 하는 일

1. RPM을 받고 sha256을 확인한다. RPM 헤더의 아키텍처가 대상과 다르면 실패한다.
2. `dnf5 install -y --setopt=tsflags=noscripts`로 설치한다. 의존성은 Fedora 저장소에서 받는다. 스크립트릿은 실행하지 않는다.
3. `/opt/Grok Bot` 전체를 `/usr/lib/grokbot/app`으로 옮긴다.
4. `/usr/lib/grokbot/app/chrome-sandbox`를 `4755`로 둔다.
5. `/usr/bin/grok-bot`은 그 바이너리를 Wayland로 실행하는 래퍼다.
6. `/etc/grokbot/app.conf`는 `GROKBOT_MODE=native`, `GROKBOT_APP_ID=grok-bot`, `GROKBOT_EXEC=/usr/bin/grok-bot`이다.
7. `grokbot://`와 `sand://`의 기본 핸들러는 `grok-bot.desktop`이다. `http`/`https`는 키오스크와 다른 Firefox 프로필인 `grokbot-open-browser`에 남긴다.

RPM이 원래 두는 데스크톱 파일:

```text
Exec=grok-bot %U
StartupWMClass=grok-bot
MimeType=x-scheme-handler/grokbot;x-scheme-handler/sand;
```

`Exec=grok-bot`은 `/usr/bin/grok-bot` 래퍼를 탄다. 래퍼가 붙이는 인자는 `--ozone-platform=wayland`와 `--enable-features=UseOzonePlatform`이다. 키오스크라 `--start-fullscreen`도 붙인다.

### 스크립트릿을 실행하지 않는 이유

`rpm -qp --scripts`로 본 `%post`는 다음을 한다.

- `update-alternatives`로 `/usr/bin/grok-bot`을 `/opt/Grok Bot/grok-bot`에 연결한다. 경로에 공백이 있으면 Electron의 setuid `chrome-sandbox`가 그 경로를 쓰지 못한다.
- 사용자 네임스페이스가 없으면 `chrome-sandbox`를 `4755`로, 있으면 `0755`로 둔다. 그 파일은 공백이 있는 경로에 있다.
- AppArmor 프로파일을 복사한다. 이 이미지는 Fedora bootc다.
- `/etc/yum.repos.d/grok-bot.repo`를 만든다. 업데이트는 그 저장소가 아니라, 고정 URL로 이미지를 다시 만들어 `bootc upgrade`하는 쪽이다.

그래서 스크립트릿은 건너뛰고, 위 2–5단계가 같은 일을 이미지에 맞게 한다. `rpm -q grok-bot`은 패키지가 설치됐다고 보지만, `rpm -V`는 `/opt` 아래 파일이 옮겨져서 어긋난다. 앱 업데이트는 이미지 재빌드다.

### `/opt`에서 옮기는 이유

이 베이스에서 `/opt`는 `/var/opt`로 이어져 있다. 이미지 빌드 때 `/var`에 쓴 내용은 부팅 디스크에 안 남을 수 있다. 그래서 실행 파일은 `/usr/lib/grokbot/app`에 둔다. 같은 이유로 경로의 공백도 사라진다.

### 의존성

x86_64 RPM의 `grok-bot`을 `readelf -d`로 본 `NEEDED`와, RPM `Requires`에 적힌 패키지를 `build_files/build.sh`의 `dnf5 install`에 Fedora 이름으로 넣었다. `gtk3`, `nss`, `nspr`, `at-spi2-core`, `at-spi2-atk`, `libnotify`, `libXtst`, `libuuid`, `libXScrnSaver`, `libXcomposite`, `libXdamage`, `libXfixes`, `libXrandr`, `mesa-libgbm`, `libxkbcommon`, `libdrm`, `alsa-lib`, `cups-libs`, `libsecret`, `systemd-libs`. RPM 설치가 같은 패키지를 다시 골라도 된다. 패키지 이름이 틀리면 이미지 빌드가 실패한다. 이 환경에는 Fedora 저장소가 없어 그 설치는 돌리지 않았다.

`--no-sandbox`는 넣지 않는다. 샌드박스가 이 구성에서 실제로 붙는지는 부팅해서 봐야 한다. SELinux가 setuid 헬퍼를 막을 수 있다.

## 플레이스홀더

```bash
GROKBOT_DISABLE_BUNDLED_APP=1 just build
```

설정은 다음과 같다.

```text
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
```

`GROKBOT_WEB_URL`이 비어 있으면 Firefox 키오스크가 `file:///usr/share/grokbot/placeholder.html`을 연다. 안내 페이지다. 로그인 페이지가 아니다.

웹 앱 주소는 플레이스홀더일 때만 쓴다. 네이티브 RPM을 넣는 빌드에서는 무시한다.

```bash
GROKBOT_DISABLE_BUNDLED_APP=1 \
GROKBOT_WEB_URL='https://확인된-주소' \
just build
```

허용하는 스킴은 `https://`, `http://`, `file://`다. 따옴표, `$`, 백틱, 역슬래시, 줄바꿈이 있으면 빌드가 실패한다.

## 다른 페이로드

고정 RPM 대신 다른 파일을 넣을 수 있다. sha256은 필수다. 없으면 빌드가 실패한다.

| 변수 | 의미 |
|---|---|
| `GROKBOT_APP_SOURCE` | `https://` URL 또는 빌드 컨텍스트 안의 절대 경로. `http://`는 거부 |
| `GROKBOT_APP_SHA256` | 64자리 hex. 고정 RPM을 쓸 때 비우면 위에 적힌 값을 쓴다 |
| `GROKBOT_APP_KIND` | `auto`, `appimage`, `rpm`, `deb`, `flatpak`, `binary`. 기본 `auto` |
| `GROKBOT_APP_EXEC` | 공식 grok-bot RPM이 아닌 rpm, deb, binary의 실행 파일 절대 경로 |
| `GROKBOT_FLATPAK_ID` | kind가 `flatpak`일 때 앱 id (`org.example.App`) |
| `GROKBOT_TARGET_ARCH` | `amd64` 또는 `arm64`. 고정 RPM 선택과 RPM 아키텍처 검사 |
| `GROKBOT_DISABLE_BUNDLED_APP` | `1`이면 고정 RPM을 받지 않는다 |
| `GROKBOT_WEB_URL` | 페이로드가 없을 때만 사용 |

공식 grok-bot RPM(파일 목록에 `/opt/Grok Bot/grok-bot`이 있는 패키지)은 `GROKBOT_APP_EXEC` 없이 위 설치 절차를 탄다. 다른 rpm은 `dnf5 install`이고 실행 경로가 필요하다. deb는 `ar`로 `data.tar.*`를 푼다. AppImage 래퍼는 `/dev/fuse`가 없으면 `APPIMAGE_EXTRACT_AND_RUN=1`을 켠다. Flatpak 파일은 `flatpak install --system`이다. 런타임이 더 필요하면 빌드가 실패한다. 그 실패는 숨기지 않는다.

```bash
GROKBOT_APP_SOURCE='https://example.invalid/Other.AppImage' \
GROKBOT_APP_SHA256='0123...abcd' \
just build
```

### 저장소에 파일을 두는 방법

```text
grokbot-app/payload
grokbot-app/SHA256SUMS
```

`SHA256SUMS`는 `sha256sum` 출력이다. 첫 필드만 읽는다. `payload`와 `SHA256SUMS`는 `.gitignore`에 있다. 이 파일이 있으면 고정 URL보다 우선한다.

## 세션이 남는 곳

| 모드 | 위치 | 지우는 방법 |
|---|---|---|
| placeholder | `~/.local/share/grokbot/firefox-profile` | 앱 안의 로그아웃, 또는 `grokbot-sign-out` |
| 외부 http(s) 링크 | `~/.local/share/grokbot/external-browser-profile` | 키오스크 프로필과 일부러 분리했다 |
| native | Electron이 홈 아래에 쓰는 곳 | 앱 안의 로그아웃. `grokbot-sign-out`은 파일을 지우지 않고 안내만 한다 |

홈은 `/var/home/grokbot`다. 이미지 빌드 때 만든 `/var`는 부팅 이미지에 안 남을 수 있어서, `systemd-tmpfiles`가 디렉터리만 다시 만든다. 이미 있는 파일은 그대로 둔다.

`grokbot://`와 `sand://`는 `grok-bot.desktop`으로 연다. `xdg-open`의 `http`/`https`는 `grokbot-open-browser`다. 그 브라우저는 `--new-window`와 키오스크와 다른 프로필을 쓴다. 로그인 창이 키오스크 Firefox 탭으로 흡수되던 2026-07-13 문제를 피하기 위한 것이다. 네이티브 앱이 연 그 창은 `Alt+F4`로 닫고, `Alt+G`로 Grok Bot에 돌아온다. 예전의 `wm.py`가 창을 자동으로 닫던 동작은 이 트리에 없다.

`grokbot` 계정 비밀번호는 잠겨 있다. tty1 자동 로그인만 된다. 복구는 Anaconda에서 만든 관리자 계정과 `Ctrl+Alt+F2`다.

## 아직 부팅으로 확인하지 못한 것

- Wayland에서 실제 `app_id`가 `grok-bot`인지. 데스크톱 파일의 `StartupWMClass=grok-bot`을 그렇게 읽는다. 다르면 `Alt+G`가 창을 못 찾고, `Alt+Tab`은 동작한다.
- `chrome-sandbox`의 setuid가 SELinux enforcing에서 허용되는지.
- Electron이 세션을 홈의 어느 디렉터리에 쓰는지.
