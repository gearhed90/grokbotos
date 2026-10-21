# 기여 안내 / Contributing

Grok Bot OS에 관심을 가져 주셔서 고맙습니다. / Thanks for your interest in Grok Bot OS.

> 보안 문제는 이슈가 아니라 [SECURITY.md](SECURITY.md)의 절차로 비공개 신고해 주세요.
> Report security issues privately as described in [SECURITY.md](SECURITY.md), not as issues.

## 어디에 올리나 / Where things go

- **이슈는 재현된 버그 전용** / **Issues are for verified bugs only.** 재현 절차와 `bootc status`를 함께 적어 주세요. / Include reproduction steps and `bootc status`.
- 기능 제안, 아이디어 / Feature ideas: [Discussions → Ideas](https://github.com/head77x/grokbotos/discussions/categories/ideas)
- 질문, 설치 도움 / Questions and install help: [Discussions → Q&A](https://github.com/head77x/grokbotos/discussions/categories/q-a)
- 보안 / Security: [SECURITY.md](SECURITY.md) (비공개 신고 / private reporting)
- 큰 변경은 PR 전에 Discussions에서 먼저 이야기한다. / Discuss large changes in Discussions before opening a PR.
- AI 에이전트는 [AGENTS.md](AGENTS.md)도 따른다. / AI agents also follow [AGENTS.md](AGENTS.md).

## 시작하기 / Getting started

1. 저장소를 포크하고 `main`에서 브랜치를 만든다. / Fork the repo and branch from `main`.
2. 변경하고, 아래처럼 로컬에서 테스트한다. / Make your change and test it locally (below).
3. PR을 연다. PR 템플릿의 체크리스트를 채운다. / Open a pull request and fill in the template checklist.

## 로컬 테스트 / Local testing

GitHub Actions를 바꾸거나 직접 돌릴 필요는 없다. PR에서는 `check.yml`이 같은 테스트를 자동으로 돌린다.
You do not need to change or run GitHub Actions yourself. `check.yml` runs the same tests on every PR.

```bash
bash tests/run-tests.sh        # 셸 테스트 + grokbotd 단위 테스트 + shellcheck(설치된 경우)
                               # shell tests + grokbotd unit tests + shellcheck (if installed)
python3 tests/grokbotd/test_grokbotd.py   # OS API만 / OS API only
```

필요한 것 / Requirements: `bash`, `python3` (표준 라이브러리만 / stdlib only), `iproute2`(`ss`, `ip`), 가능하면 `shellcheck`.
`tests/test-install-grokbot-app.sh`는 `rpmbuild`가 있어야 한다. / needs `rpmbuild`.

이미지나 부팅을 바꿨다면 / If you changed the image or boot flow:

```bash
just build                     # podman으로 이미지 빌드 / build the image with podman
```

그리고 VM에서 부팅해 확인하고([`agents/skills/vm-testing.md`](agents/skills/vm-testing.md), `tools/vm/`, [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)), 바뀐 화면마다 스크린샷을 PR에 붙인다.
Then boot it in a VM ([`agents/skills/vm-testing.md`](agents/skills/vm-testing.md), `tools/vm/`, [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)) and attach a screenshot of every changed screen to the PR.

## 규칙 / Ground rules

- `.github/workflows/`는 메인테이너와 먼저 이야기하지 않고 바꾸지 않는다. / Do not change `.github/workflows/` without discussing it first.
- 이미지 이름 `grokbotos` / `grokbotos-arm64`, `IMAGE_NAME=grokbotos`, S3 접두사 `grokbotos/`는 바꾸지 않는다(README의 "이름을 바꾸지 않은 것"). / Keep the image names and S3 prefix as they are (see README).
- 비밀값, 토큰, 개인 테스트 계정을 커밋하지 않는다. / Never commit secrets, tokens or personal test accounts.
- OS API 메서드를 추가할 때는 `os-api.schema.json`, 백엔드, 테스트, `docs/OS_API.md`를 함께 고친다. / A new OS API method needs the schema, a backend, tests and `docs/OS_API.md` in the same PR.

## 커밋 스타일 / Commit style

- 제목 한 줄은 짧게, 무엇을 바꿨는지 적는다. 한국어나 영어 모두 된다. 필요하면 범위를 앞에 붙인다.
  / Short one-line subject saying what changed, in Korean or English, optionally prefixed with a scope.
  - 예 / e.g. `grokbotd: sway보다 먼저 시작해도 wayland_display 보고`, `README: fix install link`
- 본문에는 왜 바꿨는지, 어떻게 확인했는지 적는다. / Use the body for why, and how you verified it.
- 한 커밋에는 하나의 논리적 변경만 담는다. / One logical change per commit.

## 병합 정책 / Merge policy

- 모든 변경은 PR로 들어온다. `main`에 직접 push하지 않는다(브랜치 보호). / Every change lands through a PR. There are no direct pushes to `main` (branch protection).
- 병합 조건: `check.yml` 통과, 검증 내용(테스트, VM, 스크린샷) 기재, 메인테이너 리뷰. / To merge, a PR needs a passing `check.yml`, a description of how it was verified (tests, VM, screenshots) and maintainer review.
- **병합은 메인테이너 `head77x`만 한다.** 사람이든 AI 에이전트든 다른 누구도 병합하지 않는다. / **Only the maintainer `head77x` merges.** No one else merges, human or AI agent.
- 방향에 맞지 않는 PR은 이유를 적고 닫을 수 있다. / A PR that does not fit the project's direction may be closed, with the reason given.

## 릴리스 정책 / Release policy

- `main`에 병합되면 CI가 이미지를 빌드해 GHCR에 올린다: `latest`와 날짜 태그(`YYYYMMDD`, `latest-YYYYMMDD`, `YYYYMMDD-<sha>`). / Each merge to `main` builds and pushes the image to GHCR with `latest` and dated tags (`YYYYMMDD`, `latest-YYYYMMDD`, `YYYYMMDD-<sha>`).
- 사용자에게 보이는 변경은 GitHub Releases의 **릴리스 노트**에 적는다. 보안 수정과 신고자 크레딧도 포함한다. / User-visible changes are written up in **release notes** on GitHub Releases, including security fixes and reporter credits.
- 설치된 시스템은 `sudo bootc upgrade`로 받는다. 문제가 생기면 `sudo bootc rollback`으로 이전 이미지로 돌아가거나, 날짜 태그로 고정할 수 있다(`sudo bootc switch ghcr.io/head77x/grokbotos:YYYYMMDD`). / Installed systems update with `sudo bootc upgrade`. If something breaks, `sudo bootc rollback` returns to the previous image, or you can pin a dated tag (`sudo bootc switch ghcr.io/head77x/grokbotos:YYYYMMDD`).

## 라이선스 / License

이 프로젝트는 [Apache License 2.0](LICENSE)이다. 기여는 Apache-2.0 제5조에 따라 같은 라이선스로 제출된 것으로 본다(inbound = outbound). DCO 서명(`Signed-off-by`)이나 CLA는 필요 없다.
This project is licensed under [Apache-2.0](LICENSE). Under section 5 of the license, contributions are submitted under the same license (inbound = outbound). No DCO sign-off or CLA is required.

Grok Bot 앱은 이 저장소의 일부가 아니며 별도 라이선스를 따른다. 이미지는 그 앱을 받아 넣기만 한다([`docs/GROKBOT_APP.md`](docs/GROKBOT_APP.md)). Apache-2.0은 이 저장소의 코드와 설정에만 적용된다.
The Grok Bot app is not part of this repository and is licensed separately. The image only downloads and bundles it (see [`docs/GROKBOT_APP.md`](docs/GROKBOT_APP.md)). Apache-2.0 covers only the code and configuration in this repository.
