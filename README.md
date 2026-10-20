# Grok Bot OS

설치하고 켜면 화면에 Grok Bot만 나오는 Linux다. Fedora bootc(`quay.io/fedora/fedora-bootc`) 위에 만들었고, 미리 설치된 앱은 sway 키오스크에서 전체화면으로 도는 **Grok Bot Linux 앱 하나**뿐이다.

사용자는 가지고 있는 Grok Bot 계정으로 로그인하거나 새로 구독하고, 그 다음부터는 이 PC를 Grok Bot으로 쓴다. 다른 앱이 필요하면 Flathub에서 설치하거나(`grokbot-install flatpak <app-id>`), Grok Bot이 이 PC에서 만든 앱을 사용자 홈(`~/Apps`)에 둔다(`grokbot-install local ...`). OS 업데이트는 bootc가 한다.

> **English summary.** Grok Bot OS is a Fedora bootc image whose only preinstalled app is the Grok Bot Linux app, running full screen in a sway kiosk. Users sign in with their Grok Bot account (or subscribe), install extra apps via Flatpak / `grokbot-install`, or have Grok Bot build apps locally. Updates come from bootc.

템플릿 골격은 [ublue-os/image-template](https://github.com/ublue-os/image-template)에서 왔다. 저장소 이름은 `head77x/oais`이고, 컨테이너 이미지 이름도 `oais` / `oais-arm64` 그대로다(아래 "이름을 바꾸지 않은 것"). 제품 이름은 Grok Bot OS다.

## 현재 상태

**2026-10-20 로컬 VM에서 확인** (x86_64, QEMU, KVM 없이 TCG 에뮬레이션, UEFI. 디스크는 `bootc install to-filesystem`으로 수동 생성):

- [x] `podman build`로 이미지 빌드, Grok Bot 0.71.2 RPM 설치 (#12에서 빌드 오류 2건 수정)
- [x] 부팅 → tty1 자동 로그인 → sway → 전체화면 Grok Bot 로그인 화면 (`app_id` `grok-bot`, Wayland)
- [x] `Alt+Space` → "앱 실행" 런처(fuzzel)가 Grok Bot 위에 표시, Firefox는 목록에서 숨김
- [x] 런처에서 앱(Foot) 실행, `Alt+G`로 전체화면 Grok Bot 복귀
- [x] `bootc status`, `grokbot-factory-reset --dry-run`

**아직 확인하지 않은 것:**

- [ ] SELinux enforcing (VM 디스크는 라벨 없이 설치되어 `selinux=0`으로 부팅)
- [ ] bootc-image-builder로 만든 ISO / qcow2 설치
- [ ] KVM 속도에서의 동작, 실제 하드웨어 ([`docs/HARDWARE.md`](docs/HARDWARE.md))
- [ ] Grok Bot 계정 로그인 이후 화면

2026-07-09에는 **이전 이미지**를 Apple Silicon UTM(arm64)에 ISO로 설치하고 `bootc status`까지 확인했다. 지금 이미지의 arm64 부팅은 확인하지 않았다.

## 문서

- 로컬에서 빠르게 테스트하기: [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)
- 로드맵: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- 하드웨어와 드라이버: [`docs/HARDWARE.md`](docs/HARDWARE.md)
- 결정 기록: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- 앱을 이미지에 넣는 방법: [`docs/GROKBOT_APP.md`](docs/GROKBOT_APP.md)
- 설치 명령 규격: [`docs/GROKBOT_INSTALL.md`](docs/GROKBOT_INSTALL.md)
- 독(위·아래·왼쪽·오른쪽), 창 배치: [`docs/DOCK.md`](docs/DOCK.md)

## 이 트리에서 부팅되는 것

**기본 이미지는 Grok Bot 0.71.2 RPM을 넣는다.** amd64와 arm64 둘 다다. 빌드가 아키텍처에 맞는 고정 URL을 받고, sha256이 다르면 실패한다. 설치 경로와 체크섬은 [`docs/GROKBOT_APP.md`](docs/GROKBOT_APP.md)에 있다.

`GROKBOT_DISABLE_BUNDLED_APP=1`이면 Firefox 키오스크가 로컬 안내 페이지(`file:///usr/share/grokbot/placeholder.html`)를 연다. 그 페이지는 로그인 화면이 아니다. 다른 AppImage, rpm, deb, Flatpak, 실행 파일을 체크섬과 함께 넣으면 그 바이너리를 실행한다. 없는 앱을 만들어 넣지 않는다.

로그인, 구독, 로그아웃은 Grok Bot(또는 그 웹 앱)이 한다. 이 OS는 계정을 만들지 않고 비밀번호를 저장하지 않는다.

## 부팅 순서

```text
getty tty1 자동 로그인 (사용자 grokbot, 비밀번호 없음)
  -> sway  (바탕화면 아이콘 없음, 창 테두리 없음)
    -> grokbot-dock   (가장자리 독, 기본: 아래 독 아이콘만. docs/DOCK.md)
    -> grokbot-kiosk  (앱이 끝나면 1초 뒤 다시 실행)
      -> grokbot-launch
           native (기본):  /usr/bin/grok-bot  (Wayland 래퍼)
           placeholder: Firefox --kiosk --no-remote (전용 프로필)
```

키:

| 키 | 동작 |
|---|---|
| `Super+Space`, `Alt+Space` | 설치한 앱 목록 (fuzzel) |
| `Super+G`, `Alt+G` | Grok Bot 창으로 포커스 |
| `Alt+Tab`, `Alt+Shift+Tab` | 모든 작업 공간의 창 전환 |
| `Alt+F4`, `Super+Q` | 보고 있는 창 닫기 |
| `Ctrl+Alt+F2` | 설치할 때 만든 관리자 콘솔 |

창은 전체화면이 아니라 독을 뺀 영역에 최대화된다. Grok Bot은 작업 공간 1, 다른 앱은 각자 새 작업 공간에 열린다. 독 위치·모드는 `grokbot-dock-config`로 바꾼다.

Alt 조합을 같이 둔 이유: UTM 같은 VM은 Super 키를 넘기지 않는 경우가 있었다.

세션 데이터는 `/var/home/grokbot`에 남는다. tmpfiles가 매 부팅에 이 디렉터리를 만들되, 들어 있는 파일은 지우지 않는다. 네이티브 앱의 로그아웃은 앱 안에서 한다. `grokbot-sign-out`은 플레이스홀더 Firefox 프로필만 지운다. `http`/`https`는 그 프로필과 다른 Firefox 창으로 열고, `grokbot://`와 `sand://`는 Grok Bot으로 연다. `Alt+G`는 `app_id`가 `grok-bot`인 창으로 돌아온다.

## 공장 초기화

```bash
sudo grokbot-factory-reset --dry-run        # 지울 목록만 출력
sudo grokbot-factory-reset --confirm RESET  # /var/home/grokbot 안의 내용만 지움
```

`--confirm RESET` 없이는 아무것도 지우지 않고, `--dry-run`이 있으면 항상 지우지 않는다. `/usr`와 bootc 배포는 건드리지 않는다. 전체 `/var` 초기화와 첫 부팅 재실행은 아직 없다([`docs/DECISIONS.md`](docs/DECISIONS.md)).

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
system_files/usr/local/bin/grokbot-*  세션, 실행, 설치, 로그아웃, 공장 초기화 초안
disk_config/                          ISO / qcow2
.github/workflows/build.yml           GHCR oais, oais-arm64
.github/workflows/build-disk.yml      qcow2 / anaconda ISO
.github/workflows/check.yml           셸 테스트. 이미지는 안 만듦
docs/
tests/
legacy/orchestrator/                  예전 OAIS(AI-OS) 오케스트레이터 코드. 이미지에 없음, 참고용
```

## 로컬 빌드

Podman과 just가 있는 Linux 머신에서. VM으로 띄우는 순서는 [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

```bash
just build
```

아키텍처를 직접 지정할 때 (CI는 매트릭스 값을 넘긴다):

```bash
GROKBOT_TARGET_ARCH=amd64 just build   # 또는 arm64
```

플레이스홀더만 넣을 때:

```bash
GROKBOT_DISABLE_BUNDLED_APP=1 just build
```

다른 바이너리를 넣을 때는 체크섬이 필수다. 없으면 빌드는 실패한다.

```bash
GROKBOT_APP_SOURCE='https://example.invalid/GrokBot.AppImage' \
GROKBOT_APP_SHA256='64자리hex' \
just build
```

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
