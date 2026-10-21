# 바탕화면 (Desktop layer)

원칙: **바탕화면에는 아이콘을 절대 두지 않는다.** 앱으로 가는 길은 독([`DOCK.md`](DOCK.md)), `Alt+Space` 런처, Grok Bot뿐이다.

## 층 구성 (아래에서 위로)

```text
background  배경화면        grokbot-desktop -> swaybg          (지금 있음)
bottom      위젯 층          grokbot-widgets (가칭)             (아직 없음, 아래 설계)
창          Grok Bot과 앱    작업 공간 1 = Grok Bot, 앱은 각자 새 작업 공간
top         독               grokbot-dock (layer-shell, exclusive zone)
overlay     런처             fuzzel --layer overlay
```

배경화면은 창이 덮지 않는 곳에서만 보인다. 예: 아직 창이 없는 작업 공간, 독 뒤(독 배경은 반투명).

## 배경화면

- 기본 이미지: `/usr/share/grokbot/wallpapers/lofoten.jpg`. 출처와 라이선스(CC0)는 같은 폴더의 `CREDITS.md`.
- 설정: `/etc/grokbot/desktop.conf`(기본값), `~/.config/grokbot/desktop.conf`(사용자).

```ini
[desktop]
wallpaper = /usr/share/grokbot/wallpapers/lofoten.jpg
mode = fill        # fill | fit | stretch | center | tile
color = #000000    # 이미지가 없거나 읽을 수 없을 때
```

- 바꾸기 (사용자 또는 Grok Bot):

```bash
grokbot-wallpaper show
grokbot-wallpaper set ~/Pictures/my.jpg fill
grokbot-wallpaper color '#101418'
grokbot-wallpaper reset
```

`grokbot-wallpaper`는 사용자 설정을 쓰고 swaybg를 끝낸다. sway가 띄운 `grokbot-desktop` 루프가 새 설정으로 swaybg를 다시 띄운다. 로그: `~/.local/share/grokbot/desktop.log`.

## 나중에: 위젯 층 (아이콘 없음)

아직 구현하지 않았다. 넣을 때의 규칙:

- layer-shell **bottom** 층에 둔다. 배경화면 위, 창 아래. 창이 열리면 가려진다. exclusive zone은 잡지 않는다(독과 다르다).
- 위젯만 둔다: 시계, 날씨, Grok Bot 상태나 알림 요약 같은 정보 카드. **앱이나 파일을 여는 아이콘, 바로 가기는 넣지 않는다.**
- 설정은 같은 `desktop.conf`의 `[widgets]` 섹션과 사용자 덮어쓰기, CLI는 `grokbot-wallpaper`와 같은 방식(파일 쓰기 + 프로세스 재시작/SIGHUP).
- 프로세스는 `grokbot-desktop`이 함께 띄우거나 sway `exec` 한 줄을 더 둔다.
