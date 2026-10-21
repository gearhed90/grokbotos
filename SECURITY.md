# 보안 정책 / Security Policy

## 지원 버전 / Supported versions

| 버전 / Version | 지원 / Supported |
|---|---|
| `main` 브랜치와 최신 이미지 (`ghcr.io/head77x/grokbotos:latest`, `ghcr.io/head77x/grokbotos-arm64:latest`) / `main` and the latest images | ✅ |
| 그 밖의 브랜치, 태그, 예전 이미지 / other branches, tags, older images | ❌ |

보안 수정은 `main`에만 들어가고 다음 이미지 빌드로 배포된다. 설치된 시스템은 `sudo bootc upgrade`로 받는다.
Fixes land on `main` and ship with the next image build. Installed systems pick them up with `sudo bootc upgrade`.

## 무엇이 취약점인가 / What counts as a vulnerability

취약점은 **의미 있는 보안 경계를 넘는 것**이다. 버그나 하드닝 제안은 이슈나 Discussions에 올린다.
A vulnerability is something that **crosses a meaningful security boundary**. Ordinary bugs and hardening ideas go to issues or Discussions.

특히 / In particular:

- **grokbotd OS API 권한 / permissions**: 허용받지 않은 호출자·origin이 메서드를 부르거나, capability 검사를 우회하거나, 감사 로그를 피하거나 위조하는 것. / A caller or origin calling a method it was not granted, bypassing a capability check, or evading or forging the audit log.
- **웹 앱 origin 격리 / Web app origin isolation**: 한 웹 앱이 다른 origin의 권한, 데이터, 세션을 얻는 것, 또는 `127.0.0.1:7311`을 웹 페이지에서 악용하는 것(DNS rebinding, CSRF 등). / One web app gaining another origin's permissions, data or session, or a web page abusing `127.0.0.1:7311` (DNS rebinding, CSRF, …).
- **Grok Bot 제어 / control**: 사용자가 허락하지 않은 쪽이 Grok Bot 세션, 명령, MCP 도구를 조종하는 것. / An unauthorized party driving the Grok Bot session, its commands or its MCP tools.
- 일반 사용자에서 root로 권한 상승, 이미지·업데이트 체인(서명, `bootc upgrade`) 변조. / Privilege escalation to root, or tampering with the image or update chain (signatures, `bootc upgrade`).

취약점이 아닌 것 / Not a vulnerability: 이미 같은 권한을 가진 사용자가 자기 시스템을 바꾸는 것, 단순 크래시(경계를 넘지 않는 경우), 스캐너 결과만 있는 보고. / A user changing their own system with privileges they already have, plain crashes that cross no boundary, or bare scanner output.

## 취약점 신고 / Reporting a vulnerability

**공개 이슈, PR, 토론에 취약점을 올리지 마세요.** / **Do not open public issues, pull requests or discussions for vulnerabilities.**

신고는 **GitHub 비공개 취약점 신고로만** 받는다. 이메일 창구는 없다. / Reports are accepted **only through GitHub private vulnerability reporting**. There is no email channel.

- **Security** 탭 → **Advisories** → **Report a vulnerability**: <https://github.com/head77x/grokbotos/security/advisories/new>

다음을 적어 주세요 / Please include:

- 영향받는 구성 요소와 넘은 경계 / the affected component and the boundary crossed (예 / e.g. `grokbotd` capability, origin isolation)
- 재현 절차, 이미지 digest 또는 커밋 / steps to reproduce, the image digest or commit (`bootc status`)
- 개념 증명(최소한으로) / a minimal proof of concept
- 예상 영향과 전제 조건 / the expected impact and preconditions
- 알고 있다면 완화 방법 / a mitigation, if known

## 책임 있는 공개 / Responsible disclosure

- 수정이 배포되기 전에는 공개하지 말아 주세요. 기본 공개 시점은 신고 후 90일 또는 수정 배포 시점 중 빠른 쪽이며, 협의해 조정할 수 있다. / Please do not disclose before a fix ships. The default is 90 days after the report or when the fix ships, whichever comes first, adjustable by agreement.
- 다른 사람의 데이터나 시스템에는 접근하지 말고, 자신의 설치본에서만 시험하세요. / Test only on your own installations, never against other people's data or systems.

## 대응 목표 / Response targets

| 단계 / Step | 목표 / Target |
|---|---|
| 접수 확인 / Acknowledge | 3 영업일 / 3 business days |
| 판정(유효성, 심각도) / Triage (validity, severity) | 7일 / 7 days |
| 수정 배포 / Fix released | 심각 30일, 그 외 90일 / critical 30 days, others 90 days |

목표이지 보장은 아니다. 진행 상황은 advisory에서 알린다. / These are targets, not guarantees. Progress is posted on the advisory.

## 크레딧 / Credits

수정이 배포되면 GitHub Security Advisory를 공개하고, 원하는 신고자는 **릴리스 노트**와 아래 목록에 이름을 올린다. / When a fix ships, we publish a GitHub Security Advisory and, if the reporter wishes, credit them in the **release notes** and in the list below.

### 감사한 분들 / Hall of thanks

_(아직 없음 / none yet)_

## 범위 / Scope

대상 / In scope:

- 이 저장소의 코드와 이미지 구성. 특히 로컬 OS API(`grokbotd`: unix 소켓, `127.0.0.1:7311`, origin 권한, 감사 로그). 자세한 보안 모델은 [`docs/OS_API.md`](docs/OS_API.md)에 있다.
  / Code and image configuration in this repository, especially the local OS API (`grokbotd`). See [`docs/OS_API.md`](docs/OS_API.md) for its security model.

대상 아님 / Out of scope:

- Grok Bot 앱 자체, Fedora 패키지, Flathub 앱의 취약점. 각 업스트림에 신고하세요.
  / Vulnerabilities in the Grok Bot app itself, Fedora packages or Flathub apps. Report those upstream.
- 물리적 접근이나 이미 root를 가진 공격자를 전제로 한 문제. / Issues that require physical access or an attacker who already has root.
