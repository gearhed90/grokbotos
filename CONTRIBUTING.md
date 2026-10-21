# 기여 안내 / Contributing

Grok Bot OS에 관심을 가져 주셔서 고맙습니다. / Thanks for your interest in Grok Bot OS.

> 보안 문제는 이슈가 아니라 [SECURITY.md](SECURITY.md)의 절차로 비공개 신고해 주세요.
> Report security issues privately as described in [SECURITY.md](SECURITY.md), not as issues.

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

그리고 [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)의 방법으로 VM에서 부팅해 확인하고, 가능하면 PR에 스크린샷을 붙인다.
Then boot it in a VM as described in [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md), and attach screenshots to the PR if you can.

## 규칙 / Ground rules

- `.github/workflows/`는 메인테이너와 먼저 이야기하지 않고 바꾸지 않는다. / Do not change `.github/workflows/` without discussing it first.
- 이미지 이름 `oais` / `oais-arm64`, `IMAGE_NAME=oais`, S3 접두사 `oais/`는 바꾸지 않는다(README의 "이름을 바꾸지 않은 것"). / Keep the image names and S3 prefix as they are (see README).
- 비밀값, 토큰, 개인 테스트 계정을 커밋하지 않는다. / Never commit secrets, tokens or personal test accounts.
- OS API 메서드를 추가할 때는 `os-api.schema.json`, 백엔드, 테스트, `docs/OS_API.md`를 함께 고친다. / A new OS API method needs the schema, a backend, tests and `docs/OS_API.md` in the same PR.

## 커밋 스타일 / Commit style

- 제목 한 줄은 짧게, 무엇을 바꿨는지 적는다. 한국어나 영어 모두 된다. 필요하면 범위를 앞에 붙인다.
  / Short one-line subject saying what changed, in Korean or English, optionally prefixed with a scope.
  - 예 / e.g. `grokbotd: sway보다 먼저 시작해도 wayland_display 보고`, `README: fix install link`
- 본문에는 왜 바꿨는지, 어떻게 확인했는지 적는다. / Use the body for why, and how you verified it.
- 한 커밋에는 하나의 논리적 변경만 담는다. / One logical change per commit.

## 라이선스 / License

이 프로젝트는 [Apache License 2.0](LICENSE)이다. 기여는 Apache-2.0 제5조에 따라 같은 라이선스로 제출된 것으로 본다(inbound = outbound). DCO 서명(`Signed-off-by`)이나 CLA는 필요 없다.
This project is licensed under [Apache-2.0](LICENSE). Under section 5 of the license, contributions are submitted under the same license (inbound = outbound). No DCO sign-off or CLA is required.
