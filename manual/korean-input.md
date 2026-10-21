# 한글 입력 / Korean input

한글 입력은 기본으로 켜져 있다(fcitx5 + 한글). / Korean input is on by default (fcitx5 + Hangul).

| 키 / Key | 동작 / Action |
|---|---|
| `한/영` | 한글 ↔ 영어 / Korean ↔ English |
| `Shift+Space` | 한글 ↔ 영어 |
| 오른쪽 `Alt` / Right `Alt` | 한글 ↔ 영어 (많은 노트북의 한/영 키 / the 한/영 key on many laptops) |

- Grok Bot 앱, Firefox, 터미널(foot)에서 쓸 수 있다. / Works in the Grok Bot app, Firefox and the terminal (foot).
- 기본 자판은 두벌식, 시작은 영어. / Default layout is Dubeolsik; input starts in English.
- 바꾸기 / Customize: `~/.config/fcitx5/profile`, `~/.config/fcitx5/config` (fcitx5 형식 / format). 기본값은 `/etc/xdg/fcitx5/`.
- Grok Bot은 `input.status` OS API로 현재 입력기(예: `hangul`)를 읽을 수 있다. 입력한 글자는 API로 나가지 않는다. / Grok Bot can read the current input method through `input.status`. Typed text is never exposed.
