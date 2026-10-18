# grokbot-app/

이미지를 만들 때 Grok Bot Linux 앱을 넣는 자리다. 비어 있으면 빌드는 아키텍처에 맞는 고정 RPM URL을 받는다. `GROKBOT_DISABLE_BUNDLED_APP=1`이면 플레이스홀더다. 이 저장소에 RPM 파일을 커밋하지 않는다.

파일을 넣을 때 이름은 `payload` 하나다.

```text
grokbot-app/payload          # AppImage, rpm, deb, flatpak, 또는 실행 파일
grokbot-app/SHA256SUMS       # sha256sum 출력 한 줄. 페이로드가 있으면 필수
```

확장자가 없는 `payload`는 종류를 알 수 없으므로 빌드 인자 `GROKBOT_APP_KIND`가 필요하다.
URL로 받는 방법은 `docs/GROKBOT_APP.md`에 있다.

`payload`와 `SHA256SUMS`는 용량이 클 수 있다. 저장소에 커밋하지 않아도 된다. CI에서 빌드 인자로 URL과 체크섬을 넘기면 된다.
