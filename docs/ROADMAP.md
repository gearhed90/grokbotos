# Grok Bot OS 로드맵

설치 후 첫 화면은 Grok Bot이다. 사용자는 기존 계정으로 로그인하거나 구독하고, Grok Bot에게 일을 시킨다. 앱이 필요하면 Flathub에서 설치하거나, Grok Bot이 만든 앱을 사용자 홈에 둔다. OS 업데이트는 bootc가 한다.

체크박스는 두 가지를 섞지 않는다. 코드가 트리에 있으면 `[x]`와 함께 "코드"라고 적는다. 가상머신이나 실기기에서 확인하지 않았으면 그 사실을 같은 줄에 적는다. 이전 AI-OS 이미지에서 확인한 사실을 이 이미지의 확인으로 적지 않는다.

이전 오케스트레이터(상태 머신, 앱 레지스트리, Claude/Grok/Ollama CLI, 개발 에이전트, 웹 셸)는 [`legacy/orchestrator/`](../legacy/orchestrator/)에 있다. 이미지에 들어가지 않는다. 이유는 [`DECISIONS.md`](./DECISIONS.md) 2026-10-18 항목.

## 지금 구조

```text
fedora-bootc
  -> tty1 자동 로그인 (grokbot)
  -> sway 키오스크
  -> grokbot-kiosk (종료되면 재실행)
  -> grokbot-launch
       /etc/grokbot/app.conf 가 placeholder 이면 Firefox 키오스크
       native 이면 /usr/lib/grokbot/grokbot-native
```

앱 설치는 사용자 권한 `grokbot-install` 하나다. Flatpak은 `--user`와 Flathub만. Grok Bot이 만든 앱은 `~/Apps/<id>`와 `~/.local/share/applications/grokbot-local-<id>.desktop`.

## Phase A — 부팅하면 Grok Bot 키오스크

- [x] tty1 자동 로그인 → sway → 단일 실행 진입점 `grokbot-launch` (코드). 계정 이름은 `grokbot`. 홈 디렉터리는 매 부팅 tmpfiles로 보장하고 내용은 유지한다. 이 패턴은 2026-07-11 검은 화면의 수정이다. **이 조합의 부팅은 미확인.**
- [x] 앱이 죽으면 `grokbot-kiosk`가 1초 뒤 다시 실행 (코드). sway는 exec 자식을 재시작하지 않는다.
- [x] 패널, 창 테두리, 데스크톱 아이콘 없음 (sway 설정, 코드).
- [x] 플레이스홀더: 페이로드가 없으면 Firefox `--kiosk`가 로컬 안내 페이지를 연다 (코드, 셸 테스트). **화면 출력은 미확인.**
- [ ] 이 이미지를 amd64와 arm64 VM에서 설치하고, 재부팅 뒤 키오스크만 보이는지 확인. 2026-07-09 UTM 확인은 이전 이미지다.
- [ ] Plymouth 스플래시. 넣지 않았다.

**완료 기준:** 클린 설치 → 재부팅 → 다른 데스크톱 없이 Grok Bot(또는 플레이스홀더)만 보인다. 앱을 죽여도 다시 뜬다.

## Phase B — 로그인 / 구독

- [x] 이 OS의 계정 시스템, 토큰 저장, OAuth 클라이언트를 두지 않는다 (코드에서 제거, `legacy/`로 이동).
- [x] 플레이스홀더 세션은 `~/.local/share/grokbot/firefox-profile`에 남는다 (코드). `grokbot-sign-out`은 그 디렉터리만 지운다 (셸 테스트).
- [ ] `GROKBOT_WEB_URL`에 실제 Grok Bot 웹 앱 주소를 넣어 첫 화면이 그 로그인/구독 페이지인지 확인. 주소는 아직 정해지지 않았다.
- [ ] 네이티브 Grok Bot Linux 빌드를 이미지에 넣어, 그 앱의 로그인/구독이 첫 화면인지 확인. 바이너리 출처는 정해지지 않았다.
- [ ] 재부팅 뒤 로그인 세션이 유지되는지, 로그아웃 뒤 다시 로그인 화면인지 실기 확인.

**완료 기준:** 설치 직후 첫 화면에서 Grok Bot 로그인 또는 구독을 끝낼 수 있고, 재부팅 후에도 그 세션이 홈 디렉터리에 남아 있다.

## Phase C — 앱 설치

- [x] `grokbot-install flatpak <app-id>`: `flatpak install --user -y flathub` (코드, 가짜 flatpak으로 테스트). 임의 URL 설치는 없다.
- [x] `grokbot-install local`: `~/Apps/<id>`에 복사하고 `.desktop`을 쓴다. 심볼릭 링크와 홈 밖 경로는 거부한다 (셸 테스트).
- [x] `Super+Space` / `Alt+Space`는 fuzzel, `Super+G` / `Alt+G`는 Grok Bot 포커스, `Alt+Tab`과 `Alt+F4`는 유지 (sway 설정, 코드). **키 입력은 미확인.**
- [ ] Flathub에서 앱 하나를 실제로 설치하고 fuzzel로 연 뒤 Grok Bot으로 돌아오는 실기 확인.
- [ ] Grok Bot이 `grokbot-install`을 직접 호출하는 연결. 헬퍼와 규격만 있다. Grok Bot 앱 쪽 호출은 앱이 이미지에 들어온 뒤에 맞춘다.

**완료 기준:** Grok Bot(또는 복구 셸)이 Flathub 앱과 로컬 앱을 설치하고, 키오스크에서 그 앱과 Grok Bot을 오갈 수 있다.

## Phase D — Grok Bot이 만든 앱의 권한

로컬 앱은 지금 사용자 `grokbot` 권한으로 그대로 실행된다. Flatpak 앱만 Flatpak 샌드박스를 탄다. 이 단계는 아직 없다.

- [ ] 로컬 앱의 기본 권한: 파일, 네트워크, 장치.
- [ ] 격리 수단 선택 (bubblewrap, Flatpak 매니페스트, 또는 다른 것).
- [ ] Grok Bot이 설치를 요청할 때 사용자가 권한을 볼 수 있는 경로.
- [ ] 홈 디렉터리 전체를 지우는 테스트 앱이 막히는지 확인.

**완료 기준:** Grok Bot이 만든 앱이 허용하지 않은 경로와 장치에 닿지 못한다.

## Phase E — 업데이트, 롤백, 하드웨어 이미지

- [x] bootc 이미지 빌드와 GitHub Actions(`build.yml`, `build-disk.yml`)가 amd64와 arm64를 각각 `oais`, `oais-arm64`로 내도록 정의되어 있다. 디스크 이미지는 qcow2와 anaconda ISO. **이 워크플로 정의는 유지했다. 이 전환 커밋으로 이미지를 만들어 보지는 않았다.** 이전 커밋의 GHCR 푸시와 arm64 ISO 설치는 이전 이미지에서 확인됐다.
- [ ] `bootc upgrade`와 이전 배포로 롤백이 이 이미지에서 동작하는지 확인.
- [ ] `bootc switch`로 기존 bootc 시스템을 이 이미지로 바꾸는 경로. 이전에도 안 했다.
- [ ] amd64 실기 또는 VM 부팅. 이전 확인은 arm64 UTM뿐이었다.
- [ ] 정해진 하드웨어에 구워 넣는 팩토리 이미지.

**완료 기준:** 설치된 시스템이 레지스트리의 다음 이미지로 원자적으로 올라가고, 실패하면 이전 부팅으로 돌아온다.

## 이전 이미지에서 이미 확인된 것

아래는 Grok Bot OS 전환 **이전** 이미지의 기록이다. 다시 확인하기 전에는 이 로드맵의 완료로 세지 않는다.

- [x] `ghcr.io/head77x/oais`(amd64)와 `ghcr.io/head77x/oais-arm64`(arm64) 게시. 커밋 `429f595` 빌드.
- [x] arm64 anaconda ISO와 qcow2 빌드 성공 (Actions run `28999368347`).
- [x] 2026-07-09 Apple Silicon UTM에서 arm64 ISO 클린 설치, 재부팅, 로그인, `bootc status`가 `ghcr.io/head77x/oais-arm64:latest` (digest `sha256:a6461e54...`).
- [x] 그 계열에서 tty1 자동 로그인 뒤 sway가 뜨고 화면이 그려진 적이 있다. 당시 화면은 지금 지운 웹 셸이었다. 검은 화면, Firefox가 로그인 페이지를 같은 창에 흡수한 문제는 `docs/DECISIONS.md`에 있고, 그때 넣은 수정(tmpfiles, 별도 브라우저 창, Alt+Tab, Alt+F4)은 이 트리에 남아 있다.

## 다음에 실기에서 볼 것

1. 이 브랜치가 `main`에 합쳐진 뒤 `build.yml` → `build-disk.yml`이 녹색인지.
2. arm64 ISO를 UTM에 설치하고 재부팅한다.
3. 첫 화면이 플레이스홀더 안내인지, 패널이 없는지.
4. `Alt+Space`로 fuzzel이 뜨는지. Super가 안 먹으면 Alt가 되는지.
5. `~grokbot/.local/share/grokbot/shell.log`에 Firefox 오류가 없는지 (`Ctrl+Alt+F2`).
6. 그 다음에야 `GROKBOT_WEB_URL` 또는 실제 바이너리를 넣어 다시 부팅한다.
