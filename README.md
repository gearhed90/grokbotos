# Grok Bot OS

설치하고 켜면 화면에 Grok Bot만 나오는 Linux다. 사용자는 가지고 있는 Grok Bot 계정으로 로그인하거나 새로 구독하고, 그 다음부터는 이 PC를 Grok Bot으로 쓴다. 일을 시키고, 필요하면 앱을 설치하거나 Grok Bot이 만든 앱을 이 PC에 둔다.

기반은 [bootc](https://github.com/bootc-dev/bootc)와 `quay.io/fedora/fedora-bootc`다. 템플릿 골격은 [ublue-os/image-template](https://github.com/ublue-os/image-template)에서 왔다.

저장소 이름은 `head77x/oais`이고, 컨테이너 이미지 이름도 `oais` / `oais-arm64` 그대로다. 제품 이름만 Grok Bot OS다.

- 로드맵: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- 결정 기록: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- 실기에서만 할 일: [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)
- 앱을 이미지에 넣는 방법: [`docs/GROKBOT_APP.md`](docs/GROKBOT_APP.md)
- 설치 명령 규격: [`docs/GROKBOT_INSTALL.md`](docs/GROKBOT_INSTALL.md)

## 이 트리에서 부팅되는 것

**플레이스홀더다.** 이 저장소와 공개된 곳에 Grok Bot Linux 빌드가 없다. 빌드할 때 앱을 지정하지 않으면 Firefox 키오스크가 로컬 안내 페이지(`file:///usr/share/grokbot/placeholder.html`)를 연다. 그 페이지는 로그인 화면이 아니다.

`GROKBOT_WEB_URL`을 넣으면 그 주소가 첫 화면이 된다. AppImage, rpm, deb, Flatpak, 실행 파일을 체크섬과 함께 넣으면 `/usr/local/bin/grokbot-launch`가 그 바이너리를 실행한다. 없는 앱을 만들어 넣지 않는다.

로그인, 구독, 로그아웃은 Grok Bot(또는 그 웹 앱)이 한다. 이 OS는 계정을 만들지 않고 비밀번호를 저장하지 않는다.

## 부팅 순서

```text
getty tty1 자동 로그인 (사용자 grokbot, 비밀번호 없음)
  -> sway  (패널 없음, 창 테두리 없음)
    -> grokbot-kiosk  (앱이 끝나면 1초 뒤 다시 실행)
      -> grokbot-launch
           placeholder: Firefox --kiosk --no-remote (전용 프로필)
           native:      /usr/lib/grokbot/grokbot-native
```

키:

| 키 | 동작 |
|---|---|
| `Super+Space`, `Alt+Space` | 설치한 앱 목록 (fuzzel) |
| `Super+G`, `Alt+G` | Grok Bot 창으로 포커스 |
| `Alt+Tab`, `Alt+Shift+Tab` | 창 순환 |
| `Alt+F4` | 보고 있는 창 닫기 |
| `Ctrl+Alt+F2` | 설치할 때 만든 관리자 콘솔 |

Alt 조합을 같이 둔 이유: UTM 같은 VM은 Super 키를 넘기지 않는 경우가 있었다.

세션 데이터는 `/var/home/grokbot`에 남는다. tmpfiles가 매 부팅에 이 디렉터리를 만들되, 들어 있는 파일은 지우지 않는다. 플레이스홀더의 브라우저 쿠키는 `~/.local/share/grokbot/firefox-profile`에 있다. 플레이스홀더에서 로그아웃하려면 `grokbot-sign-out`을 실행한다. 이 명령은 그 프로필만 지운다. 네이티브 앱은 앱 안의 로그아웃을 쓴다.

## 디렉터리

```text
Containerfile                         fedora-bootc 이미지
Justfile                              just build, 디스크 이미지
oais.env                              IMAGE_NAME=oais (유지)
build_files/build.sh                  패키지, os-release, grokbot 계정
build_files/install-grokbot-app.sh    페이로드 또는 플레이스홀더
grokbot-app/                          로컬 페이로드 자리. 기본은 비어 있음
system_files/etc/grokbot/app.conf     grokbot-launch 가 읽는 설정
system_files/etc/sway/config          키오스크
system_files/usr/local/bin/grokbot-*  세션, 실행, 설치, 로그아웃
disk_config/                          ISO / qcow2
.github/workflows/build.yml           GHCR oais, oais-arm64
.github/workflows/build-disk.yml      qcow2 / anaconda ISO
.github/workflows/check.yml           셸 테스트. 이미지는 안 만듦
docs/
tests/
legacy/orchestrator/                  이전 AI-OS 오케스트레이터. 이미지에 없음
```

## 로컬 빌드

Podman, bootc, just가 있는 머신에서. 이 개발 샌드박스에서는 이미지가 안 만들어진다.

```bash
just build
```

웹 앱을 첫 화면으로:

```bash
GROKBOT_WEB_URL='https://확인된-주소' just build
```

바이너리:

```bash
GROKBOT_APP_SOURCE='https://example.invalid/GrokBot.AppImage' \
GROKBOT_APP_SHA256='64자리hex' \
just build
```

체크섬이 없으면 빌드는 실패한다.

## 여기서 확인한 것, 실기가 필요한 것

2026-07-09에 **이전 이미지**를 Apple Silicon UTM(arm64)에서 ISO로 설치하고, 재부팅한 뒤 `bootc status`가 `ghcr.io/head77x/oais-arm64:latest`를 가리키는 것까지 확인했다. tty1 자동 로그인 뒤 sway가 뜨는 것도 그 계열에서 봤다.

이 전환 이후 이미지(플레이스홀더, `grokbot` 계정, Flatpak, 앱 전환)는 여기서 부팅하지 않았다. KVM도 podman 빌드도 없다. 이 환경에서 돌리는 것은 `tests/run-tests.sh`, shellcheck, 워크플로 YAML, `just --list` / `just --dry-run`이다.

## 이름을 바꾸지 않은 것

| 그대로 | 이유 |
|---|---|
| GitHub 저장소 `head77x/oais` | 저장소 이름 |
| `ghcr.io/head77x/oais`, `ghcr.io/head77x/oais-arm64` | 기존 pull, 서명, 디스크 빌드 |
| `oais.env`의 `IMAGE_NAME=oais` | 워크플로가 이 값으로 이미지 이름을 만든다 |
| `disk_config/iso.toml`의 `ghcr.io/head77x/oais:latest` | `build-disk.yml`이 이 문자열을 바꿔 넣는다 |
| S3 접두사 `oais/`, 아티팩트 `oais-<타입>-<아키텍처>` | 받아 가던 경로 |
| `/etc/os-release`의 `ID=fedora` | bootc와 패키지 도구가 ID를 본다 |

`NAME` / `PRETTY_NAME` / `VARIANT`는 Grok Bot OS다.
