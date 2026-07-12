# AI-OS 프로젝트 로드맵 (ToDo)

> 목표: 프롬프트 기반으로 AI가 프로그램을 생성·실행·처리하고 결과만 제공하는 "AI 오케스트레이션 레이어"를 갖춘, SteamOS 스타일의 설치형 커스텀 리눅스 배포판을 만든다. 데스크톱/미니PC를 1차 타겟으로 하고, 이후 전용 하드웨어 및 모바일로 확장한다.

**진행 원칙**: 아래 Phase는 순서대로 진행하되, 각 Phase는 독립적으로 검증 가능한 결과물(Deliverable)을 갖는다. 한 Phase를 완료(체크리스트 전부 완료 + Acceptance Criteria 통과)하기 전에는 다음 Phase로 넘어가지 않는다.

> **진행 현황 메모 (최종 갱신 2026-07-12)**: **Phase 1 완료** — Apple Silicon Mac + UTM에서 클린 설치 → 재부팅 → 로그인 → `bootc status` 확인까지 실제 검증. **Phase 2는 오케스트레이터 프로토타입까지 구현, 아직 완료는 아님** — Task Spec, 앱 레지스트리(태그 매칭만, 임베딩 미착수), 폐쇄루프 상태 머신, LLM 연동(클라우드 CLI 서브프로세스 + 로컬 Ollama), 2.5~2.6 개발 플래닝/후보 검색·평가/경로 A·B·C까지는 실제 코드와 자동 테스트로 검증되지만, 2.7(테스트/검수)·2.8(레지스트리 등록)이 없어 신규 개발 경로는 "코드 생성"에서 끝난다. **Phase 4 부팅 셸은 사용자 요청으로 Phase 2 완료보다 먼저 진행 중** — 웹 기반 GUI 셸(`orchestrator/webshell/`, Claude Design 참고 디자인), 모든 아이콘 클릭이 슬래시 명령(`/llm`, `/token`, `/system`, `/cli`, `/help`) 제출과 완전히 동일하게 동작하는 통일 아키텍처, 우측 실시간 CLI 로그 패널, sway 창 자동 정리(`webshell/wm.py`)까지 구현. 하루 동안 여러 차례 실기 검증 라운드를 거치며 검은 화면 부팅 실패, LLM 연결 무응답, UI/아키텍처 전면 재설계, npm 설치 타임아웃/권한 문제, 이미지 빌드 실패, 로그인 실패 시 출력 불가시성, **잘못된 CLI 명령어(`claude login`은 존재하지 않고 실제로는 `claude auth login`)**, 로그인 성공 후 창을 닫고 돌아갈 방법이 없던 문제까지 순차적으로 진단·수정했다 (상세 경위는 [`DECISIONS.md`](./DECISIONS.md) 2026-07-11 항목들 전부 참고 — 실제 로그/스크린샷 기반 진단이 대부분이라 사후 학습 가치가 큼). **이 최신 상태 전체를 한 번에 통과하는 완전한 실기 검증은 아직 없음** — 각 개별 버그는 재현·수정됐지만, 다음 재부팅에서 "부팅 → GUI 렌더링 → 아이콘 클릭 → 브라우저 로그인 → AI-OS 셸 복귀 → 프롬프트 입력"이 끊김 없이 되는지는 여전히 미확인. 178개 자동 테스트 통과. 아직 미착수인 것: 임베딩/벡터 검색(2.3 tier 2~3), 2.7~2.8(테스트/검수·등록 에이전트), Phase 3 샌드박스, 클라우드/로컬 라우팅 정책, 음성 입력(STT), `/system network`의 실제 설정 변경(현재는 상태 조회만), systemd 데몬화, 아키텍처 문서. 로컬 머신에서만 가능한 작업은 [`LOCAL_SETUP.md`](./LOCAL_SETUP.md), 프로토타입의 실제/스텁 여부 표는 [`../orchestrator/README.md`](../orchestrator/README.md) 참고. 이 파일의 체크박스는 실제 진행 상태를 반영하도록 계속 갱신한다.

---

## Phase 0 — 프로젝트 기반 준비

**목표**: 개발 환경과 저장소 구조를 갖춘다.

- [x] GitHub Repository 생성 — `head77x/oais` (조직 대신 개인 계정 저장소로 진행)
- [ ] 로컬 개발 머신에 Podman, `bootc`, `just`, `git` 설치 — **사용자 로컬 머신에서 필요** (`docs/LOCAL_SETUP.md` 참고, 이 개발 샌드박스는 KVM/특권 컨테이너 미지원)
- [x] 베이스 배포판 결정: **Fedora Atomic (bootc) — `quay.io/fedora/fedora-bootc`** (데스크톱 없는 최소 베이스, 멀티아키텍처(amd64+arm64) 지원. 처음엔 `ghcr.io/ublue-os/base-main`이었으나 amd64 전용이라 arm64(Apple Silicon) 빌드/테스트가 막혀서 2026-07-09에 변경 — 근거는 `DECISIONS.md`)
- [x] `ublue-os/image-template` 베이스 템플릿 확보 — 별도 포크 대신 템플릿 내용을 이 저장소에 직접 이식 (동일 목적 달성, 저장소 단일화)
- [ ] 로컬 VM(QEMU/libvirt)에서 베이스 이미지 부팅 테스트 — **사용자 로컬 머신에서 필요**

**Deliverable**: 로컬에서 부팅되는 미수정 베이스 bootc 이미지
**Acceptance Criteria**: `sudo bootc status` 정상 출력 확인 — 사용자 로컬 머신에서 검증 필요

---

## Phase 1 — 최소 커스텀 이미지 빌드 (Hello World OS)

**목표**: 아무 기능 없이 "내 이름이 박힌 OS"를 처음부터 끝까지 빌드→배포→설치까지 1회 완주한다.

- [x] `Containerfile`에 최소 커스터마이징 추가 (`tmux`, `htop` 설치, `/etc/os-release`에 `AI-OS` 반영)
- [x] GitHub Actions(`build.yml`)로 이미지 자동 빌드 → GHCR 푸시 확인 — `ghcr.io/head77x/oais`(amd64) + `ghcr.io/head77x/oais-arm64`(arm64) 둘 다 게시 확인됨 (커밋 `429f595` 빌드, cosign 서명 포함 정상 완료)
- [x] `bootc-image-builder`로 ISO / QCOW2 이미지 생성 (`build-disk.yml`) — arm64 anaconda-iso/qcow2 둘 다 빌드 성공 확인 (run `28999368347`)
- [x] VM에 ISO로 신규 설치 테스트 — **완료 (2026-07-09)**: 사용자가 Apple Silicon Mac(UTM, arm64 네이티브 가상화)에서 ISO로 클린 설치 → 재부팅 → 로그인 성공. `bootc status`로 `ghcr.io/head77x/oais-arm64:latest` 부팅 확인 (digest `sha256:a6461e54...`)
- [ ] 기존 시스템에서 `sudo bootc switch <내 이미지>` 로 전환 테스트 — 아직 미실행 (신규 ISO 설치 경로만 검증됨; 기존 bootc 시스템에서 리베이스하는 별도 시나리오는 테스트 안 됨). Phase 1 완료를 막지는 않음(Acceptance Criteria는 ISO 설치 경로만 요구), 여유 있을 때 검증 권장

**Deliverable**: 다운로드 가능한 ISO 1개 + 컨테이너 레지스트리에 게시된 이미지 — **달성**
**Acceptance Criteria**: 클린 VM에 ISO로 설치 → 재부팅 → 로그인 성공 — **달성 (2026-07-09, Apple Silicon Mac + UTM, arm64)**

> **Phase 1 사실상 완료.** 유일하게 안 한 건 `bootc switch` 리베이스 테스트(체크리스트 항목이지만 Acceptance Criteria엔 없음) — 이건 언제든 나중에 확인 가능. amd64 경로는 이미지 자체는 게시됐지만 실제 부팅 테스트는 안 함(테스트 환경이 Apple Silicon이라 arm64로 진행).

---

## Phase 2 — AI 에이전트 오케스트레이션 레이어 설계 (폐쇄루프 파이프라인)

**목표**: 부팅 즉시 프롬프트/음성 입력만 노출하고, 요청을 "기존 앱 재사용 → (없으면) 신규 개발 → 테스트/검수 → 등록 → 실행"까지 자동으로 완결하는 폐쇄루프(Closed-loop) 파이프라인을 구축한다. (아직 하드닝/샌드박싱 전, 로컬 프로토타입 단계 — 실제 격리 실행은 Phase 3에서 통합)

### 전체 흐름 요약

```
[부팅] → Plymouth 스플래시 → 전용 풀스크린 셸(프롬프트+음성 입력만 노출)
   │
   ▼
[2.1 입력 수집] 텍스트 프롬프트 또는 음성(STT) 입력
   │
   ▼
[2.2 의도 분석] LLM이 요청을 구조화된 작업 스펙(Task Spec)으로 변환
   │
   ▼
[2.3 앱 레지스트리 검색] 로컬 앱/서비스 DB에서 동일/유사 기능 검색
   │
   ├─ 있음 → [2.4 기존 앱 실행] → 결과 반환 → (종료)
   │
   └─ 없음 → [2.5 개발 플래닝] 요구사항을 구현 계획으로 분해
                │
                ▼
             [2.6 개발 에이전트] 코드 직접 생성 OR 오픈소스 검색·설치
                │
                ▼
             [2.7 테스트/검수 에이전트] 자동 테스트 + 스펙 부합 여부 검증
                │
        ┌───────┴───────┐
      실패(N회 미만)      성공
        │                 │
        ▼                 ▼
     [2.6로 피드백 회귀]  [2.8 앱 레지스트리 등록] (메타데이터+실행매니페스트 저장)
                              │
                              ▼
                          [2.9 신규 앱 실행] → 결과 반환 → (종료)

  ※ 실패가 N회(기본 3회) 초과 시 → 무한루프 방지를 위해 사용자에게 상황 보고 후 추가 지시 요청
```

### 2.1 입력 레이어 (프롬프트 + 음성)

- [x] 부팅 직후 자동 실행되는 전용 풀스크린 세션 설계 — `sway`(컴포지터, 데스크톱 요소 없음) + Firefox `--kiosk` 모드로 로컬 웹 UI(`orchestrator.webshell_cli`)를 fullscreen 표시, `aios` 계정으로 tty1 자동 로그인. **실기 검증 1회 완료**: 첫 arm64 이미지가 실제로 tty1 autologin → sway → 셸까지 부팅되는 것을 사용자가 UTM에서 확인함 (단, 그때 뜬 건 구버전 텍스트 셸 — 아래 참고). 이번 GUI 웹 셸 자체는 아직 미검증. Plymouth 스플래시와의 실제 전환 시퀀스도 미검증
- [x] 프롬프트 입력 UI 구현 — **Claude Design 프롬프트 화면을 참고해 전면 재설계**: 다크 테마, 중앙 프롬프트 카드 + 아래 명령/앱 썸네일 타일 그리드(`orchestrator/webshell/static/`). 사용자가 이전 버전(텍스트 메뉴, 이후 첫 GUI 버전)을 모두 거부하고 "OS라면 제대로 된 구조"를 요구 — 그 결과 아이콘 클릭이 곧 슬래시 명령 제출이 되도록 통일한 아키텍처로 재구현 (아래 명령 프롬프트 통일 항목 참고). `onboarding_cli.py`의 텍스트 입력 루프는 헤드리스(SSH/복구 콘솔)용으로 유지
- [ ] 음성 입력(STT) 연동: 로컬(Whisper.cpp 등) / 클라우드 STT 중 결정, 오프라인 우선 여부 정책 수립 — 미착수
- [x] 입력 완료 트리거(엔터/음성 종료 감지) 정의 — 웹 UI는 폼 제출(엔터 또는 버튼 클릭) → `/api/prompt`, 음성 트리거는 미착수 (STT 자체가 없음)
- [x] **(ToDo 원문엔 없던 항목, 사용자 지시로 선행)** LLM 연동 온보딩: Claude/Grok/Ollama/커스텀 CLI 선택 → 설치 → 로그인 → 저장, 로직은 `orchestrator/orchestrator/onboarding.py` (텍스트 셸 `onboarding_cli.py`와 웹 셸 `webshell/` 양쪽이 공유)
- [x] **(ToDo 원문엔 없던 항목, 사용자 지시로 추가)** 명령/프롬프트 처리 통일 — 어떤 아이콘을 누르든 `/api/prompt`로 슬래시 명령이 제출되는 것과 완전히 동일하게 동작 (`webshell/commands.py` 라우터). 내장 명령: `/llm [id]`(LLM 목록/연결, `custom` 포함), `/token claude <토큰>`, `/system`/`/system network`(`nmcli` 기반)/`/system info`, `/cli`(실제 `foot` 터미널 창 실행), `/help`
- [x] **(ToDo 원문엔 없던 항목, "연결 중..."만 뜨고 진행 상황이 안 보인다는 사용자 피드백으로 추가)** 실시간 CLI 로그 패널 — 화면 우측에 설치/로그인 등 백그라운드 작업의 실제 진행 상황을 실시간으로 표시 (`webshell/logbuf.py`, `/api/logs` long-polling). CLI 서브프로세스의 실제 stdout/stderr를 그대로 전달 (가짜 상태 메시지 아님) — 이 로그 패널 덕분에 `npm install` 타임아웃, 권한 문제, 잘못된 로그인 명령어(`claude login`→`claude auth login`) 등 여러 실제 버그를 추측이 아니라 증거로 진단·수정할 수 있었음
- [x] **(ToDo 원문엔 없던 항목, 로그인 성공 후 원래 화면으로 못 돌아가는 문제로 추가)** sway 창 자동 정리 — 로그인 플로우가 새로 띄운 브라우저 창을 완료/실패와 무관하게 자동으로 닫아 AI-OS 셸로 복귀 (`webshell/wm.py`, sway IPC 기반), `Alt+F4` 수동 폴백도 추가. 이 섹션 전체는 178개 자동 테스트로 검증(연결 로직 + 명령 라우팅 + 로그 패널 + 창 관리 + 웹 서버 전부 포함); 실제 렌더링·클릭·터미널 실행 자체는 여전히 미검증

### 2.2 의도 분석 (Intent Router)

- [x] LLM 연동 방식 결정: **하이브리드**. 클라우드(Anthropic, xAI/Grok)는 공식 CLI를 설치하고 사용자가 직접 로그인(`claude login`/`grok login`)한 뒤, 그 CLI를 서브프로세스로 호출하는 방식 — 우리가 OAuth 토큰을 직접 다루지 않음 (`docs/DECISIONS.md` 참고, `providers/claude_cli.py`, `providers/xai_grok.py`, 공통 골격 `providers/cli_subprocess.py`). 로컬은 선택 시 Ollama 자동 설치(`providers/local_ollama.py`). 남은 것: 클라우드/로컬 라우팅 기준("언제 어떤 걸 쓸지")
- [x] 사용자 요청 → 구조화된 Task Spec(목표, 입력/출력 형식, 제약조건, 필요 권한 추정)으로 변환하는 프롬프트/스키마 설계 — `orchestrator/orchestrator/task_spec.py` (dataclass) + `task_spec.schema.json` (LLM 계약용 JSON Schema)
- [ ] 모호한 요청에 대한 재질문(clarification) 규칙 정의 — `needs_clarification`/`clarification_questions` 필드와 상태 머신 단락(short-circuit) 배선은 완료, 그러나 "언제 재질문해야 하는지" 판단하는 실제 LLM 규칙은 미구현 (현재 `StubIntentAnalyzer`는 항상 `needs_clarification=False`)

### 2.3 앱 레지스트리 검색 (기존 자산 재사용)

- [x] **`apps` 메타데이터 테이블 스키마 확정** (SQLite): `orchestrator/orchestrator/registry/schema.sql` — ToDo 필드 전부 포함 (`app_id`, `name`, `description`, `capability_tags`, `input_schema`/`output_schema`, `exec_manifest`, `creation_source`, `source_ref`, `version`, `created_at`/`updated_at`, `usage_count`, `last_used_at`, `success_rate`)
- [ ] **벡터 인덱스 엔진 선정**: `sqlite-vec` vs LanceDB — 미결정
- [ ] **임베딩 모델 선정**: 미결정
- [ ] **2단계 매칭 파이프라인 구현**: (1) capability_tags 사전 필터만 구현됨 (`registry/matcher.py`, `registry/db.py:find_by_tags`) / (2) 임베딩 유사도, (3) LLM 재검증은 미구현 — 지금 신뢰도 점수는 태그 겹침 비율로만 계산되는 임시 근사치
- [x] **임계값 정책 구현**: `state_machine.py`의 `CONFIDENCE_EXECUTE=0.85`/`CONFIDENCE_ADAPTER=0.6` 분기 — 다만 위 항목대로 신뢰도 점수 자체가 아직 근사치라 실사용 임계값 튜닝은 임베딩 도입 후 재검토 필요
- [x] 동점 후보 발생 시 `success_rate` 기준 우선순위 결정 로직 추가 — `registry/db.py:find_by_tags`의 `ORDER BY overlap DESC, success_rate DESC`
- [ ] 벡터 인덱스 갱신 전략 — 벡터 인덱스 자체가 없어 해당 없음, 엔진 선정 후 진행

### 2.4 기존 앱 실행 경로

- [x] 매칭된 앱을 호출하는 인터페이스 구현 — `state_machine.py:_execute_existing` (Phase 3 샌드박스가 없어 실제 실행 대신 스텁 결과 반환 + `usage_count`/`success_rate` 갱신)
- [x] 실행 결과를 2.9와 공통되는 "결과 반환 포맷"으로 변환 — `ResultEnvelope`

### 2.5 개발 플래닝 에이전트 (신규 앱 필요 시)

- [x] Task Spec을 구현 가능한 작업 단위로 분해하는 플래닝 프롬프트/로직 설계 — `orchestrator/orchestrator/dev_agent/planning.py` (LLM 1회 호출, work_items + search_keywords + likely_runtime 산출)
- [x] 예상 소요 리소스/설치 필요 패키지 사전 산정 — 2.6 후보 검색/평가로 실질적으로 처리 (문서 의도대로 여기서는 얇게 유지)

### 2.6 개발 에이전트

- [x] **후보 검색 쿼리 생성**: `dev_agent/candidates.py` — npm(`registry.npmjs.org/-/v1/search`)/crates.io(`crates.io/api/v1/crates`)/GitHub(`api.github.com/search/repositories`)는 실제 검색 API 호출, **PyPI는 공식 검색 API가 없어서**(XML-RPC search 폐지, JSON API는 이름으로 메타데이터 조회만 가능) `lookup_pypi(name)`으로 대체 — 플래닝 단계 keyword를 패키지명으로 바로 시도
- [x] **후보 평가 로직 구현**: `dev_agent/evaluation.py` — (1) 기능 적합도는 LLM 호출로 0~1 점수, (2) 라이선스는 허용목록(MIT/Apache-2.0/BSD/ISC 등) 통과, GPL 계열은 flagged, 그 외/누락은 unknown(안전 쪽으로 unknown 처리, 임의로 안전하다고 가정 안 함), (3) 유지보수는 최근 업데이트(2년 이내) 또는 인기도(스타/다운로드 ≥50) 중 하나, (4) 보안은 OSV.dev 실제 API(`api.osv.dev/v1/query`) 조회 — 취약점 1건이라도 있으면 탈락
- [x] **경로 A (하이브리드: 설치 + 글루 코드)** — `dev_agent/path_decision.py` + `dev_agent/codegen.py:generate_wrapper` — 평가 통과 후보 중 적합도 최고점 선택, LLM으로 얇은 wrapper 코드 생성, `creation_source="hybrid"`
- [x] **경로 B (순수 코드 생성)** — `codegen.py:generate_from_scratch` — 통과 후보 없고 사용자 자격증명 신호도 없을 때, `creation_source="generated"`
- [x] **경로 C (사용자 확인 요청)** — `path_decision.py` — `estimated_permissions`에 credential/API 키 관련 신호가 있으면 재질문 (아직 휴리스틱 키워드 매칭 수준, LLM 기반 판단 아님)
- [ ] 세 경로 모두 Phase 3 샌드박스 안에서만 설치/빌드/실행이 이뤄지도록 인터페이스 고정 — **코드 생성까지만 구현, 설치/빌드/실행은 전혀 하지 않음**. 모든 `exec_manifest`가 `sandbox_profile_id="phase3-not-implemented"`를 가리켜서 하위 단계가 안전하다고 착각할 수 없게 해둠
- [x] 세 경로 공통으로 2.3 `exec_manifest` 스키마에 맞는 실행 매니페스트 산출 — `dev_agent/agent.py:_build_exec_manifest`
- [ ] 테스트 실패 피드백을 받아 재시도하는 입력 인터페이스 설계 — 2.7(테스트 에이전트)이 없어서 아직 재시도할 대상 자체가 없음

### 2.7 테스트/검수 에이전트

- [ ] Task Spec으로부터 자동 테스트 케이스를 생성하는 로직 설계 (입력값 예시 → 기대 출력 조건)
- [ ] 생성/설치된 앱을 실제로 실행해 결과가 스펙을 만족하는지 검증
- [ ] 기본적인 안전성 체크 포함 (비정상 종료, 과도한 실행시간 등 — 상세 보안 검증은 Phase 3에서 강화)
- [ ] **실패 시 재시도 루프 제어**: 최대 재시도 횟수(기본 3회) 정의, 초과 시 사용자에게 상황 보고 후 대기(무한루프 방지가 핵심)

### 2.8 앱 레지스트리 등록

- [ ] 테스트 통과한 신규 앱을 2.3의 레지스트리 DB에 등록하는 파이프라인 구현 (기능 설명 임베딩 생성 포함)
- [ ] 실행 매니페스트(실행 명령, 필요 권한, 샌드박스 프로파일) 함께 저장
- [ ] 이후 동일/유사 요청 시 2.3 검색에서 바로 매칭되는지 회귀 테스트

### 2.9 결과 반환

- [x] "결과 전달" 표준 포맷 정의 — `state_machine.py:ResultEnvelope` (`status`/`kind`/`summary`/`payload`/`source_app_id`)
- [ ] 2.4(기존 앱)와 2.8 이후(신규 앱) 경로가 동일한 결과 반환 인터페이스를 공유하도록 통합 — 2.4 쪽은 `ResultEnvelope` 공유 완료, 2.8(신규 앱 등록 후 실행)이 아직 없어 전체 통합은 미완료

### 폐쇄루프 컨트롤러

- [x] 전체 흐름을 관리하는 상태 머신(State Machine) 구현 — `orchestrator/orchestrator/state_machine.py:Orchestrator` (`RECEIVED → INTENT_ANALYSIS → REGISTRY_SEARCH → (EXECUTE_EXISTING | PLAN → DEVELOP → TEST → ...)`; `dev_provider=` 지정 시 PLAN→DEVELOP까지 `dev_agent.develop()`로 실제 실행, TEST 이후는 `DevelopmentPending` 예외로 결과(`DevelopmentResult`) 노출)
- [ ] 각 상태 전이에 타임아웃/재시도 상한 설정 — 전체 `process()` 호출 단위 타임아웃(`OrchestratorTimeout`)은 구현됨; `max_retries`는 상수로 배선만 해두었고 실제 재시도 루프는 DEVELOP 단계가 없어 아직 동작하지 않음
- [ ] 세션/메모리 관리 설계 — 미착수

### End-to-End 검증

- [ ] 프로토타입: systemd unit으로 동작하는 오케스트레이터 데몬 초안 작성 — **아직 아님**. `orchestrator/`는 CLI로만 실행되는 순수 Python 패키지이고 systemd 유닛으로 배선되지 않음
- [x] 시나리오 A 유사 검증: `orchestrator/tests/test_state_machine.py::test_scenario_a_full_tag_overlap_executes_existing_app` — 레지스트리에 미리 등록된 앱이 태그 매칭으로 바로 실행됨을 자동 테스트로 확인 (실제 STT/LLM 의도분석이 아닌 고정 Task Spec으로 상태 머신 분기만 검증한 축소판)
- [ ] 시나리오 B (신규 개발 경로): `dev_agent.develop()`이 상태 머신에 연결되어 PLAN→DEVELOP까지는 실제로 실행되고 결과(exec_manifest 등)가 `DevelopmentPending` 예외로 노출됨 확인 (`test_dev_agent_wiring.py`) — 그러나 2.7(테스트/검수)·2.8(등록)이 없어 "등록 → 실행"까지 전체 경로 완주는 여전히 불가
- [x] 시나리오 C 유사 검증: `test_scenario_c_repeat_request_reuses_same_app_without_redevelopment` — 동일 요청 재처리 시 재개발 없이 REGISTRY_SEARCH에서 즉시 매칭되는지 확인

**Deliverable**: 오케스트레이터 데몬 프로토타입 코드 + 앱 레지스트리 DB 스키마 + 아키텍처 문서(상태 다이어그램 포함)
**Acceptance Criteria**: 시나리오 A/B/C 세 가지가 모두 개발 머신에서 실제로 재현됨 (특히 C: 한 번 개발된 앱이 재사용되어 두 번째 요청부터는 개발 단계를 건너뜀)

> **미충족 상태**: `orchestrator/` (코드 + DB 스키마 + LLM 연동 + 2.5/2.6 개발 에이전트 + 상태 머신 연결)는 있으나 아키텍처 문서(상태 다이어그램)는 아직 없고, systemd 데몬화도 안 됐다. `dev_agent.agent.develop()`은 이제 상태 머신에 연결됐지만(`Orchestrator(dev_provider=...)`), 2.7(테스트/검수)·2.8(등록)이 없어 시나리오 B가 "개발"까지만 진행되고 그 결과물이 검증도 등록도 안 된 채로 끝난다(`DevelopmentPending`). 즉 Phase 2는 아직 완료가 아니다 — 다음 단계로 자연스럽게 이어지는 것은 (1) 2.7 테스트/검수 에이전트, (2) 2.8 등록 파이프라인, (3) 아키텍처 문서 작성 중 하나.

---

## Phase 3 — 실행 격리(샌드박스) 레이어

**목표**: AI가 생성한 코드를 신뢰할 수 없는 코드로 간주하고 안전하게 격리 실행한다. (프로젝트 전체에서 보안적으로 가장 중요한 단계)

- [ ] 격리 기술 결정: Bubblewrap(경량, 데스크톱 우선 권장) vs gVisor vs Firecracker microVM(강한 격리, 서버/클라우드형)
- [ ] 격리 실행 환경에 필요한 최소 런타임 이미지 구성 (Python/Node 등 언어별 실행 환경 컨테이너화)
- [ ] 파일시스템/네트워크/디바이스 접근 권한 정책 수립 (기본값: 최소 권한, 명시적 허용만 통과)
- [ ] 리소스 제한(CPU/메모리/실행 시간 타임아웃) 적용
- [ ] Phase 2 에이전트 데몬이 이 샌드박스를 통해서만 코드를 실행하도록 리팩터링
- [ ] 악성/무한루프/과도한 리소스 사용 코드에 대한 자동 차단 테스트 케이스 작성 및 검증

**Deliverable**: 샌드박스 실행 모듈 (에이전트 데몬에 통합됨)
**Acceptance Criteria**: 의도적으로 작성한 악성 테스트 스크립트(파일시스템 파괴 시도, 무한루프, 과도한 메모리 할당)가 호스트에 영향 없이 차단됨

---

## Phase 4 — 결과 전달 UI / 전용 셸

**목표**: "결과만 사용자가 원하는 방식으로 제공"하는 사용자 경험을 구현한다. (Phase 2에서 확정: 부팅 즉시 프롬프트+음성 입력만 노출되는 전용 풀스크린 셸)

- [x] 전용 컴포지터 기반 풀스크린 셸 구현 (일반 데스크톱 UI 요소 노출 안 함) — `sway` 커스텀 config(`system_files/etc/sway/config`)가 Firefox `--kiosk`로 로컬 웹 UI(`orchestrator/webshell/`)를 표시, `/cli` 명령 실행 시 `foot` 터미널도 동일하게 풀스크린. Claude Design 참고해 시각 디자인 전면 재작업 (`docs/DECISIONS.md`). Plymouth 스플래시와의 전환 시퀀스는 미검증
- [x] **(ToDo 원문엔 없던 항목, "연결 중..."만 뜨고 진행 상황이 안 보인다는 사용자 피드백으로 추가)** 우측 실시간 CLI 로그 패널 — `webshell/logbuf.py`(`LogBuffer` 링버퍼) + `GET /api/logs` long-polling. 설치/로그인 등 백그라운드 작업의 실제 stdout/stderr를 그대로 화면에 표시 (2.1 입력 레이어 섹션과 동일 항목, 여기선 "결과 전달 UI"라는 Phase 4 목표 관점에서 재기재)
- [x] **(ToDo 원문엔 없던 항목, 로그인 성공 후 원래 화면으로 못 돌아가는 문제로 추가)** sway 창 자동 정리(`webshell/wm.py`) — 이 kiosk 구성엔 창 제목표시줄/닫기 버튼이 없어서, 로그인 등 새 창을 여는 플로우가 끝나면 그 창을 sway IPC로 자동으로 닫고 셸로 복귀시킨다. `Alt+F4` 수동 폴백 병행
- [ ] 결과 렌더링 방식 설계 (텍스트, 파일 다운로드, 인라인 미리보기 등) — 텍스트 요약만 구현됨(`ResultEnvelope.summary`를 웹 UI의 결과 영역에 표시), 파일/인라인 미리보기 미착수
- [ ] 세션 히스토리/재실행/피드백(수정 요청) 흐름 설계 — 미착수
- [x] 기본 세션으로 자동 실행되는 systemd 서비스 또는 디스플레이 매니저 세션 등록 — `getty@tty1` 자동 로그인(`system_files/etc/systemd/system/getty@tty1.service.d/autologin.conf`) + `aios` 계정의 로그인 셸이 바로 `sway` 실행. 부팅 자체는 실기 검증 완료, 이번 재설계분은 미검증
- [x] Phase 2~3 파이프라인과 UI 연결 — 웹 셸의 `/api/prompt`가 연결된 provider로 실제 `Orchestrator`(2.1~2.6 전부) 호출하거나, `/`로 시작하면 내장 명령 라우터(`webshell/commands.py`)로 처리. End-to-End 데모는 아직 아님 (Phase 3 샌드박스 없어 2.6 이후 결과가 실행/검증 안 됨, 이건 이 파일 다른 섹션에 이미 기록된 기존 제약)

> **2026-07-12 기준 실기 검증 경과**: 위 체크박스들은 모두 코드 레벨로는 구현·테스트됐지만, 실제 VM 재부팅 검증 과정에서 여러 런타임 버그가 순차적으로 발견·수정됐다 — LLM 연결 무응답(연결 스레드가 예외를 삼킴), `npm install` 타임아웃(120초 고정 → 설치/프롬프트 타임아웃 분리), `npm install` 권한 오류(런타임 설치 → 빌드 타임에 이미지에 baked-in), 이미지 빌드 자체 실패(`/root` ostree 심볼릭 링크 문제 → `HOME=/tmp`), 로그인 명령 출력이 전혀 안 보이던 문제(비캡처 stdio → 로그 패널로 스트리밍), 잘못된 CLI 서브커맨드(`claude login`은 존재하지 않음 → `claude auth login`), 로그인 성공 후 창을 닫고 돌아갈 방법이 없던 문제(→ `webshell/wm.py`). 상세 경위는 [`DECISIONS.md`](./DECISIONS.md) 2026-07-11 항목 참고. **이 모든 수정을 한 번에 통과하는 연속 재부팅 검증은 아직 완료되지 않음.**

**Deliverable**: 부팅 시 자동으로 뜨는 AI 에이전트 셸/UI
**Acceptance Criteria**: 신규 설치된 시스템에서 로그인 직후 별도 설정 없이 프롬프트 입력이 가능한 상태

---

## Phase 5 — Containerfile 통합 (OS 이미지에 AI 레이어 baked-in)

**목표**: Phase 2~4에서 만든 컴포넌트를 Phase 1의 OS 이미지에 실제로 포함시킨다.

- [ ] 에이전트 데몬, 샌드박스 런타임, UI/셸을 Containerfile에 설치 단계로 추가
- [ ] `build.sh`(또는 BlueBuild 모듈)로 systemd 서비스 자동 활성화 설정
- [ ] 이미지 용량/부팅 시간 최적화 (불필요한 레이어 제거, `just rechunk` 적용)
- [ ] CI(GitHub Actions)에서 통합 이미지 자동 빌드 파이프라인 구축
- [ ] 신규 ISO로 클린 설치 후 AI 에이전트 기능 전체 재검증

**Deliverable**: AI 레이어가 내장된 배포형 OS 이미지 v0.1
**Acceptance Criteria**: 클린 설치 → 재부팅 → 프롬프트 입력 → 결과 수신까지 사용자 개입 없이 완주

---

## Phase 6 — 브랜딩 / 아이덴티티

**목표**: "내 OS/내 하드웨어"라는 정체성을 시각적·기술적으로 확립한다.

- [ ] 프로젝트명, 로고, 컬러 스킴 확정
- [ ] Plymouth 부팅 스플래시 커스터마이징
- [ ] `/etc/os-release`, 배경화면, 기본 테마 등 브랜딩 요소 일괄 적용
- [ ] Secure Boot 자체 서명 키 발급 및 서명 파이프라인 구축 (전용 하드웨어 배포 대비)
- [ ] (선택) 설치 마법사 UI 커스터마이징 (Calamares 테마 등)

**Deliverable**: 완전히 브랜딩된 부팅~설치~데스크톱 경험
**Acceptance Criteria**: 부팅 로고부터 설치 화면, 첫 로그인까지 일관된 아이덴티티 노출

---

## Phase 7 — 업데이트/배포 인프라

**목표**: 사용자가 "손쉽게 설치"하고, 이후 지속적으로 업데이트를 받을 수 있게 한다.

- [ ] 이미지 배포 채널 결정 (GHCR 지속 + 자체 다운로드 페이지)
- [ ] 자동 업데이트 메커니즘 검증 (`bootc upgrade` 기반 원자적 업데이트, A/B 롤백 동작 확인)
- [ ] 설치 가이드/다운로드 웹페이지 제작 (설치 USB 굽는 법 포함)
- [ ] 베타 테스터 그룹 모집 및 실제 하드웨어(비-VM) 설치 테스트

**Deliverable**: 공개 다운로드 페이지 + 자동 업데이트가 동작하는 v0.2
**Acceptance Criteria**: 외부 베타 테스터 1인 이상이 자신의 PC에 독립적으로 설치 성공

---

## Phase 8 — 전용 하드웨어 대응 (미니PC/핸드헬드)

**목표**: 특정 하드웨어에 사전 설치되어 나가는 "전용 기기" 형태를 준비한다.

- [ ] 타겟 하드웨어 사양 확정 (미니PC 우선 권장, 드라이버 이슈 최소화)
- [ ] 해당 하드웨어에서 GPU/Wi-Fi/전원관리 등 드라이버 호환성 검증
- [ ] 공장 출하용 이미지 프리로드 절차 수립 (이미지 플래싱 파이프라인)
- [ ] 전용 펌웨어/부트로고 적용 (OEM 협의 필요 시 별도 트랙으로 분리)

**Deliverable**: 특정 미니PC/핸드헬드 모델에 사전 설치 가능한 팩토리 이미지
**Acceptance Criteria**: 해당 하드웨어에서 전원 On → 자동 부팅 → AI 셸까지 무설정 동작

---

## Phase 9 — 모바일 확장 (postmarketOS 기반)

**목표**: 기존 스마트폰에 설치 가능한 형태로 확장한다. (전용 모바일 칩셋 하드웨어는 이후 별도 트랙)

- [ ] postmarketOS 포크 저장소 구성, `pmbootstrap` 빌드 환경 구축
- [ ] 지원 대상 기기 1~2종 선정 (메인라인 커널 지원이 좋은 기기 우선)
- [ ] 모바일용 경량 에이전트 셸 UI 설계 (Phosh/Plasma Mobile 기반)
- [ ] Phase 3 샌드박스 레이어의 모바일 리소스 제약(배터리/메모리) 대응 튜닝
- [ ] 테스트 기기 1대에 설치 후 End-to-End 검증

**Deliverable**: 모바일 기기용 AI-OS 이미지 (제한된 기기 지원)
**Acceptance Criteria**: 테스트 기기에서 기본 통화/네트워크 기능 + AI 에이전트 기능 동시 동작

---

## 부록 A — 단계별 핵심 기술 스택 요약

| Phase | 핵심 기술 |
|---|---|
| 0~1 | bootc, Podman, Universal Blue image-template, bootc-image-builder |
| 2 | LLM API/로컬 모델, STT(Whisper 등), 벡터 검색 기반 앱 레지스트리 DB, 상태 머신 오케스트레이터, 개발/테스트 에이전트 |
| 3 | Bubblewrap / gVisor / Firecracker |
| 4 | systemd 세션, 커스텀 컴포지터/셸 |
| 5 | Containerfile, BlueBuild, GitHub Actions |
| 6 | Plymouth, Secure Boot 서명, Calamares |
| 7 | GHCR, bootc upgrade, 웹 배포 페이지 |
| 8 | 팩토리 이미지 플래싱, 하드웨어 드라이버 검증 |
| 9 | postmarketOS, pmbootstrap, Phosh/Plasma Mobile |

## 부록 B — 다음 실행 단계

~~지금 시작할 것: Phase 0 → Phase 1.~~ (완료, 2026-07-08 — 아래로 대체)

**현재 상태 (2026-07-12 갱신)**: **Phase 0/1 완료** (2026-07-09, Apple Silicon Mac + UTM에서 ISO 설치 → 재부팅 → 로그인 → `bootc status` 확인까지 실제 검증). Phase 2는 오케스트레이터 프로토타입(Task Spec, 앱 레지스트리, 상태 머신, LLM 연동, 2.5/2.6 개발 플래닝·후보 검색/평가·경로 A/B/C, `develop()`↔상태 머신 연결)까지 진행, 2.7/2.8이 없어 아직 미완료.

**Phase 4 부팅 셸: 하루 동안 여러 라운드의 실기 검증 → 버그 발견 → 수정을 거쳤다.** 순서대로: (1) tty1 autologin → sway → 셸까지 뜨는 것 자체는 확인했지만 한글 깨짐 + 텍스트 메뉴였던 구버전을 로컬 웹서버 + Firefox 렌더링 GUI 셸로 전면 교체, (2) 재부팅 시 검은 화면 → 홈 디렉터리 tmpfiles + 로그 파일 + Firefox 실패 폴백 추가, (3) LLM 연결 시도해도 "연결 중..."에서 무한 대기 → 연결 스레드가 예외를 삼키던 버그 수정 + 로그 패널 신설(`webshell/logbuf.py`), (4) 로그 패널 도입 후 실제 로그로 `npm install` 120초 타임아웃 확인 → 설치/프롬프트 타임아웃 분리, (5) 그다음 로그로 `npm install` 권한 오류(exit 254) 확인 → 런타임 설치를 빌드 타임 baked-in으로 전환, (6) 그 결과 이미지 빌드 자체가 `/root` ostree 심볼릭 링크 문제로 실패 → `HOME=/tmp`로 수정, (7) 로그인 명령(`claude login`) 실행 후 출력이 전혀 안 보임 → stdio 캡처+스트리밍으로 전환, 그 과정에서 실제로는 `claude login`이라는 서브커맨드 자체가 존재하지 않고 `claude auth login`이 맞다는 게 로그로 드러나 수정, (8) 로그인 성공 후 OAuth 완료 페이지가 뜬 채로 셸로 돌아갈 방법이 없음 → `webshell/wm.py`(sway 창 자동 정리) 추가. 상세는 [`DECISIONS.md`](./DECISIONS.md) 2026-07-11 항목 전부 참고.

**중요**: 각 버그는 개별적으로 재현·수정·테스트됐지만, **이 모든 수정이 합쳐진 현재 상태 전체를 한 번의 연속된 재부팅으로 "부팅 → GUI 렌더링 → 아이콘 클릭 → 브라우저 로그인 → AI-OS 셸 복귀 → 프롬프트 입력 → 오케스트레이터 응답"까지 끊김 없이 통과시킨 적은 아직 없다.** 다음 재부팅 시도가 여전히 최우선 검증 대상이며, 사용자가 CI 빌드/부팅 로그·스크린샷을 붙여넣으면 그걸 보고 고치는 기존 방식으로 계속 진행한다.

**다음 후보**(아직 순서 미확정, 상세는 각 Phase의 미체크 항목 참고):
- **Phase 4 통합 실기 검증 (최우선)**: 위 8개 수정이 모두 반영된 최신 이미지로 처음부터 끝까지 한 번에 통과하는지 확인. 확인할 것: (1) 화면에 GUI 셸이 정상 렌더링되는지, (2) 한글이 정상 표시되는지, (3) 로그 패널에 실시간 진행 상황이 뜨는지, (4) LLM 아이콘 클릭 시 브라우저 로그인이 열리고 완료되는지, (5) 로그인 완료 후 창이 자동으로 닫히고 셸로 복귀하는지, (6) 복귀 후 프롬프트가 활성화되는지, (7) 재부팅 후에도 연결이 유지되는지
- Phase 2.7: 테스트/검수 에이전트 — 2.6이 만든 코드는 지금 아무 검증 없이 그냥 텍스트로만 존재
- Phase 2.8: 앱 레지스트리 등록 파이프라인 — 검증 통과한 결과를 2.3 DB에 실제로 등록
- Phase 2.3 tier 2~3: 임베딩 모델/벡터 인덱스 선정 — 지금 앱 매칭은 태그 겹침만으로 계산되는 임시 근사치
- Phase 1 잔여: `bootc switch` 리베이스 테스트(체크리스트 항목, Acceptance Criteria엔 불필요), amd64 경로 실제 부팅 테스트
- Phase 3 샌드박스: 지금 2.4/2.6이 전부 "Phase 3 없어서 스텁"으로 되어 있어, 실제 설치/실행이 가능해지려면 필요
