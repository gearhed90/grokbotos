# Grok Bot 앱을 이미지에 넣는 방법

런타임 진입점은 항상 `/usr/local/bin/grokbot-launch`다. sway는 이 프로그램만 실행한다. 무엇을 실행할지는 이미지 빌드 때 `/etc/grokbot/app.conf`에 적힌다. 그 파일을 쓰는 프로그램은 `build_files/install-grokbot-app.sh` 하나다.

## 지금 상태

**플레이스홀더를 쓴다.** 저장소에 Grok Bot Linux 빌드가 없고, 공개 URL도 이 트리에 없다. 페이로드 없이 빌드하면 설정은 다음과 같다.

```text
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
```

`GROKBOT_WEB_URL`이 비어 있으면 Firefox 키오스크가 `file:///usr/share/grokbot/placeholder.html`을 연다. 안내 페이지다. 로그인 페이지가 아니다.

웹 앱 주소를 알고 있으면 그것만 넣을 수 있다. 그래도 모드 이름은 `placeholder`다. 네이티브 바이너리가 아니기 때문이다.

```bash
GROKBOT_WEB_URL='https://확인된-주소' just build
```

허용하는 스킴은 `https://`, `http://`, `file://`다. 따옴표, `$`, 백틱, 역슬래시, 줄바꿈이 있으면 빌드가 실패한다.

## 네이티브 빌드

페이로드가 있으면 sha256이 필수다. 없으면 빌드가 실패한다. 체크섬이 맞을 때만 `/usr/lib/grokbot/grokbot-native` 래퍼를 만들고 `GROKBOT_MODE="native"`로 둔다. `grokbot-launch`는 그 래퍼만 exec한다. 쉘 문자열을 eval하지 않는다.

### 빌드 인자

`just build`가 환경 변수를 `--build-arg`로 넘긴다. Containerfile의 `ARG`와 이름이 같다.

| 변수 | 의미 |
|---|---|
| `GROKBOT_APP_SOURCE` | `https://` URL 또는 빌드 컨텍스트 안의 절대 경로. `http://`는 거부 |
| `GROKBOT_APP_SHA256` | 64자리 hex |
| `GROKBOT_APP_KIND` | `auto`, `appimage`, `rpm`, `deb`, `flatpak`, `binary`. 기본 `auto` |
| `GROKBOT_APP_EXEC` | rpm, deb, binary일 때 설치된 실행 파일의 절대 경로 |
| `GROKBOT_FLATPAK_ID` | kind가 `flatpak`일 때 앱 id (`org.example.App`) |
| `GROKBOT_WEB_URL` | 페이로드가 없을 때만 사용 |

`auto`는 파일 이름으로 고른다. `.AppImage`, `.rpm`, `.deb`, `.flatpak`. 확장자가 없으면 `binary`다. 저장소에 두는 파일 이름이 `payload`이면 확장자가 없으므로 `GROKBOT_APP_KIND`를 반드시 준다.

예시:

```bash
GROKBOT_APP_SOURCE='https://example.invalid/GrokBot.AppImage' \
GROKBOT_APP_SHA256='0123...abcd' \
just build
```

```bash
GROKBOT_APP_SOURCE='https://example.invalid/grokbot.rpm' \
GROKBOT_APP_SHA256='0123...abcd' \
GROKBOT_APP_KIND=rpm \
GROKBOT_APP_EXEC=/usr/bin/grokbot \
just build
```

AppImage 래퍼는 `/dev/fuse`가 없으면 `APPIMAGE_EXTRACT_AND_RUN=1`을 켠다. 이미지에는 `fuse`와 `fuse-libs`를 넣는다. AppImage가 실제로 마운트되는지는 실기에서 확인해야 한다.

rpm은 `dnf5 install`이다. deb는 `ar`로 `data.tar.*`를 풀어 루트에 푼다. 둘 다 `GROKBOT_APP_EXEC`가 필요하다. Flatpak 파일은 `flatpak install --system`이고, 실행은 `flatpak run <id>`다. 런타임이 더 필요하면 이 빌드 단계가 실패할 수 있다. 그 실패는 숨기지 않는다.

### 저장소에 파일을 두는 방법

```text
grokbot-app/payload
grokbot-app/SHA256SUMS
```

`SHA256SUMS`는 `sha256sum` 출력이다. 첫 필드만 읽는다. `payload`와 `SHA256SUMS`는 `.gitignore`에 있다. URL로 받는 쪽을 기본으로 둔다.

`GROKBOT_APP_SOURCE`가 있으면 로컬 `payload`보다 우선한다.

## 세션이 남는 곳

| 모드 | 위치 | 지우는 방법 |
|---|---|---|
| placeholder | `~/.local/share/grokbot/firefox-profile` | 앱 안의 로그아웃, 또는 `grokbot-sign-out` |
| placeholder의 외부 링크 | `~/.local/share/grokbot/external-browser-profile` | 키오스크 프로필과 일부러 분리했다 |
| native | 그 앱이 홈 아래에 쓰는 곳 | 앱 안의 로그아웃. `grokbot-sign-out`은 파일을 지우지 않고 안내만 한다 |

홈은 `/var/home/grokbot`다. 이미지 빌드 때 만든 `/var`는 부팅 이미지에 안 남을 수 있어서, `systemd-tmpfiles`가 디렉터리만 다시 만든다. 이미 있는 파일은 그대로 둔다.

`grokbot` 계정 비밀번호는 잠겨 있다. tty1 자동 로그인만 된다. 복구는 Anaconda에서 만든 관리자 계정과 `Ctrl+Alt+F2`다.

## 소유자가 정해야 하는 것

1. Grok Bot Linux 빌드의 URL, 종류, sha256, 실행 파일 경로.
2. 바이너리 전에 웹 앱을 띄울 경우 그 URL.
3. 네이티브 앱의 Wayland `app_id`. 플레이스홀더는 `firefox`다. 네이티브 래퍼는 sway에서 `grokbot`으로 포커스하려고 `GROKBOT_APP_ID=grokbot`을 넣는다. 앱이 다른 app_id를 쓰면 `Alt+G`가 그 창을 못 찾는다. `Alt+Tab`은 그대로 동작한다.
