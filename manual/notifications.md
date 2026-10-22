# 알림 / Notifications

알림은 화면 오른쪽 위에 6초 동안 보인다. 클릭하면 닫힌다. 긴급 알림(빨간 테두리)은 직접 닫을 때까지 남는다.
Notifications appear at the top right for 6 seconds. Click to dismiss. Critical ones (red border) stay until you dismiss them.

## 방해 금지 / Do Not Disturb

- `Super+Shift+N` 또는 `Alt+Shift+N`, 또는 터미널에서 `grokbot-notify-dnd` / or run `grokbot-notify-dnd` in a terminal.
- 켜져 있으면 알림이 보이지 않지만 기록에는 남는다. / While on, notifications are hidden but kept in history.
- `grokbot-notify-dnd status` → `on` / `off`.

## 설정 / Settings

기본 설정은 `/etc/grokbot/mako.conf`. 바꾸려면 `~/.config/mako/config`를 만든다(mako 형식). / Defaults live in `/etc/grokbot/mako.conf`. To change them create `~/.config/mako/config` (mako format).

Grok Bot은 `notifications.list` OS API로 앱 이름과 제목만 읽을 수 있다. 본문은 API로 나가지 않는다. / Grok Bot can read app names and titles through the `notifications.list` OS API. Bodies are never exposed.
