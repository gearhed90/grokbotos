# Onshape pad (nova-cadpad)

The Pi 5 touchscreen becomes a button panel for Onshape running on the CAD PC (Alpha).
A tap sends a signed, named action over the LAN (Wi-Fi on the Pi). The PC's
`onshape-pad-helper` presses the Onshape shortcut in the Onshape window. The Pi's USB-C is
power only and is not used.

## Pieces
- Pi: `build_files/rpi5/nova/cadpad.py` (GTK3, app_id `nova-cadpad`, fullscreen by sway rule).
  Tabs Sketch / Part Studio / Assembly / View, plus Undo / Redo / Esc / Accept / Accept + repeat.
  Status dot: green = helper up and Onshape open, yellow = helper up but Onshape closed, red = no token,
  can't reach the PC, or auth refused. Buttons marked "…" have no Onshape default shortcut and use
  Onshape's tool search (Alt+C, name, Enter).
- Open it with the **CAD** button (top-left of the Nova screen) or by asking Pixel to open
  `onshape_pad` (novad `open_app`). ✕ Close returns to Nova.
- Target: `/etc/grokbot/cadpad.conf` (`HOST=192.168.12.126`, `PORT=8790`); a user can override in
  `~/.config/grokbot/cadpad.conf`.
- PC: `tools/onshape-pad/onshape-pad-helper` + `onshape-pad-helper.service` (systemd user unit).
  X11 + xdotool, LAN sources only, HMAC-signed requests with a timestamp and replay cache, named
  actions only, keys only into the Onshape PWA window. `cadpad.py --dump-actions` writes its
  `actions.json`.

## Token (never in the image or the repo)
The PC makes a random token (`~/.config/nova/onshape-pad/token`, 0600). The Pi user needs the
same value in `~/.config/grokbot/cadpad.token` (0600). Copy it without showing it, e.g. from the PC:

    ssh grokbot@<pi-ip> grokbot-cadpad-token < ~/.config/nova/onshape-pad/token

`grokbot-cadpad-token` reads stdin, checks it is 64 hex characters, writes the file 0600 and
prints only the path. Rotating: make a new token on the PC, restart the helper, copy again.

## Shortcuts
Onshape defaults from https://cad.onshape.com/help/Content/Home/glossary.htm (plus the Extrude,
Trim and Offset help pages). If a shortcut is remapped in Onshape (My account > Preferences >
Keyboard shortcuts), change `ACTIONS` in `cadpad.py`, re-dump `actions.json` on the PC and restart
the helper.

## Tests
`tests/nova/test_cadpad.py` runs the real helper against `tests/nova/mock_xdotool.py`
(no display, no network): table vs helper filters, config, token perms, signing, replay/stale/
wrong-token refusals, focus guard (no keys outside Onshape), search actions and novad wiring.
It runs from `tests/test-rpi5-nova.sh`.
