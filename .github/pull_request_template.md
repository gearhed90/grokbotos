## 요약 / Summary

<!-- 무엇을, 왜 바꿨나요 / What changed and why -->

## 확인 / Verification

<!-- 어떻게 확인했나요: 테스트, VM 부팅, 스크린샷 / How was this verified: tests, VM boot, screenshots -->

## 체크리스트 / Checklist

- [ ] `bash tests/run-tests.sh` 통과 / passes
- [ ] `.github/workflows/`를 바꾸지 않았다(바꿨다면 이유를 적었다) / no workflow changes, or the reason is explained
- [ ] 이미지 이름 `grokbotos` / `grokbotos-arm64`와 S3 접두사를 바꾸지 않았다 / image names and S3 prefix unchanged
- [ ] 비밀값, 토큰, 개인 계정이 없다 / no secrets, tokens or personal accounts
- [ ] 동작이 바뀌었다면 문서(README, docs/)를 고쳤다 / docs updated if behaviour changed
- [ ] OS API를 바꿨다면 스키마, 테스트, `docs/OS_API.md`를 함께 고쳤다 / schema, tests and docs updated for OS API changes
