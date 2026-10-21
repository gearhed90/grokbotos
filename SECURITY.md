# 보안 정책 / Security Policy

## 지원 버전 / Supported versions

| 버전 / Version | 지원 / Supported |
|---|---|
| `main` 브랜치와 최신 이미지 (`ghcr.io/head77x/oais:latest`, `ghcr.io/head77x/oais-arm64:latest`) / `main` and the latest images | ✅ |
| 그 밖의 브랜치, 태그, 예전 이미지 / other branches, tags, older images | ❌ |

보안 수정은 `main`에만 들어가고 다음 이미지 빌드로 배포된다. 설치된 시스템은 `sudo bootc upgrade`로 받는다.
Fixes land on `main` and ship with the next image build. Installed systems pick them up with `sudo bootc upgrade`.

## 취약점 신고 / Reporting a vulnerability

**공개 이슈, PR, 토론에 취약점을 올리지 마세요.** / **Do not open public issues, pull requests or discussions for vulnerabilities.**

GitHub의 비공개 신고 기능을 사용하세요. / Use GitHub private vulnerability reporting:

1. 저장소의 **Security** 탭 → **Advisories** → **Report a vulnerability**
   (<https://github.com/head77x/grokbotos/security/advisories/new>)
2. 다음을 적어 주세요 / Please include:
   - 영향받는 구성 요소 / affected component (예: `grokbotd`, `grokbot-install`, sway 설정, 이미지 빌드)
   - 재현 절차, 이미지 digest 또는 커밋 / steps to reproduce, image digest or commit
   - 예상 영향 / expected impact
   - 알고 있다면 완화 방법 / mitigation, if known

신고는 메인테이너만 볼 수 있다. 확인하고 수정한 뒤 GitHub Security Advisory로 공개한다. 원하면 신고자를 표기한다.
Reports are visible only to maintainers. After a fix, the advisory is published on GitHub, crediting the reporter if they wish.

## 범위 / Scope

대상 / In scope:

- 이 저장소의 코드와 이미지 구성. 특히 로컬 OS API(`grokbotd`: unix 소켓, `127.0.0.1:7311`, origin 권한, 감사 로그). 자세한 보안 모델은 [`docs/OS_API.md`](docs/OS_API.md)에 있다.
  / Code and image configuration in this repository, especially the local OS API (`grokbotd`). See [`docs/OS_API.md`](docs/OS_API.md) for its security model.

대상 아님 / Out of scope:

- Grok Bot 앱 자체, Fedora 패키지, Flathub 앱의 취약점. 각 업스트림에 신고하세요.
  / Vulnerabilities in the Grok Bot app itself, Fedora packages or Flathub apps. Report those upstream.
- 물리적 접근이나 이미 root를 가진 공격자를 전제로 한 문제. / Issues that require physical access or an attacker who already has root.
