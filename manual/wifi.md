# Wi-Fi

- 유선은 자동 연결 / Wired networks connect automatically.
- 무선 / Wireless: 터미널에서 `nmtui` → "Activate a connection" → 네트워크 선택 후 비밀번호 입력 / open a terminal, run `nmtui`, choose "Activate a connection", pick a network and enter the password.
- 명령줄 / Command line: `nmcli device wifi list`, `nmcli device wifi connect "<SSID>" --ask`
- 목록이 비었을 때 / Empty list: `nmcli radio wifi on`, `nmcli device`. Broadcom `wl` 칩은 미지원 / Broadcom `wl` chips are unsupported.

> ⚠️ 독의 Wi-Fi 아이콘과 `Super+N`/`Alt+N` 단축키, 노트북 무선 펌웨어는 별도 PR(`docs/install-onboarding`)에서 추가되며 실제 무선 연결은 아직 검증되지 않았다. / The dock Wi-Fi icon, the `Super+N`/`Alt+N` shortcut and the laptop Wi-Fi firmware are added in a separate PR (`docs/install-onboarding`). Real wireless association is not yet verified.
