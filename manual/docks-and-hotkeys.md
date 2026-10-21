# 독과 단축키 / Docks & hotkeys

바탕화면에는 아이콘이 없다. 앱은 독, 런처, Grok Bot으로 연다. / There are no desktop icons. Open apps from the dock, the launcher or Grok Bot.

## 독 / Docks
- 위·아래 독은 아이콘만 표시 / top/bottom docks show icons only. 왼쪽·오른쪽 독은 아이콘만 또는 아이콘+이름 / left/right docks show icons, or icons plus labels.
- 기본은 아래 독, 아이콘만 / default: bottom dock, icons only.

```bash
grokbot-dock-config show
grokbot-dock-config set left labels   # 왼쪽 / left: 아이콘+이름 / icons + labels
grokbot-dock-config set bottom off
grokbot-dock-config icon-size 48
grokbot-dock-config reset
```

## 단축키 / Hotkeys

| 키 / Key | 동작 / Action |
|---|---|
| `Alt+Space`, `Super+Space` | 앱 런처 / app launcher |
| `Alt+G`, `Super+G` | Grok Bot으로 / back to Grok Bot |
| `Alt+Tab`, `Alt+Shift+Tab` | 창 전환 / switch windows |
| `Alt+F4`, `Super+Q` | 창 닫기 / close window |
| `Super+L`, `Alt+L` | 화면 잠금 / lock the screen ([잠금 / lock](lock-and-idle.md)) |

자세한 구현은 / Details: [`docs/DOCK.md`](../docs/DOCK.md)
