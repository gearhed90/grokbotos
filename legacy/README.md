# legacy/

2026-10-18 Grok Bot OS 전환 때 **이미지에서 떼어 낸** 이전 AI-OS 오케스트레이터다.
부팅 경로, Containerfile, `build_files/build.sh`는 이 디렉터리를 복사하거나 실행하지 않는다.

## 여기 있는 것

`legacy/orchestrator/` — 예전의 폐쇄루프 파이프라인 프로토타입.

- 상태 머신 (`state_machine.py`)
- 앱 레지스트리와 태그 매칭 (`registry/`)
- Claude / Grok / Ollama CLI 프로바이더 (`providers/`)
- 개발 에이전트 (`dev_agent/`: 플래닝, 후보 검색, 코드 생성)
- 자체 웹 셸과 슬래시 명령 (`webshell/`)
- LLM 연결 온보딩 (`onboarding.py`)

당시 자동 테스트도 같이 들어 있다. 제품 테스트가 아니다. 이미지 빌드와 CI의 `check` 워크플로는 이 테스트를 돌리지 않는다.

## 왜 지워지지 않고 여기 있나

실기에서 잡은 버그(검은 화면, `claude login` 서브커맨드, Firefox 키오스크가 로그인 창을 같은 창으로 흡수한 문제)의 원인 코드가 이 트리에 있다. 기록은 `docs/DECISIONS.md`에 남아 있고, 동작하던 수정(홈 디렉터리 tmpfiles, 기본 브라우저 래퍼, Alt+Tab / Alt+F4)은 새 세션 쪽으로 옮겨 두었다. 오케스트레이터 자체는 Grok Bot이 그 역할을 대신하므로 부팅에 연결하지 않는다.

복구가 필요하면 git 히스토리와 이 디렉터리를 본다. 다시 이미지에 넣지 않는다.

> 2026-10-21: the image/GHCR/S3 names were renamed from `oais` to `grokbotos` (see README and docs/DECISIONS.md). `oais` names in this directory are historical and left as-is.
