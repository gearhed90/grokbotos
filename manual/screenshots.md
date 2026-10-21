# 스크린샷 / Screenshots

| 키 / Key | 동작 / Action |
|---|---|
| `Print` (PrtSc) | 전체 화면 / whole screen |
| `Shift+Print` | 마우스로 영역 선택, `Esc` 취소 / drag to select an area, `Esc` cancels |

- `~/Pictures/Screenshots/screenshot-날짜_시간.png`에 저장되고, 클립보드에 복사되며, 알림이 뜬다. `Ctrl+V`로 바로 붙여 넣을 수 있다. / Saved to `~/Pictures/Screenshots/screenshot-<date>_<time>.png`, copied to the clipboard and announced with a notification. Paste with `Ctrl+V`.
- 터미널 / Terminal: `grokbot-capture full`, `grokbot-capture region`, `grokbot-capture dir`.
- Grok Bot은 `capture.status` OS API로 파일 이름과 크기만 볼 수 있다(이미지 내용은 안 나감). / Grok Bot can see file names and sizes through `capture.status` (never the image data).
