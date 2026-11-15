# Cypher: autonomy layer

Cypher is the Raspberry Pi 5 running grokbotos, and the always-running mind on it. `cypherd` keeps five drives (energy, curiosity, social, boredom, focus) that drift over time, and every 45 seconds decides whether to do something. When something changed (Zack came back, the focused app changed, the mood changed) or every 10 minutes, it asks a model to pick one action from a fixed manifest, the validator checks the choice against the locked limits, and one JSON line goes to the journal. Inspired by Pino (pinos.world). The design page is "Cypher: autonomy layer design".

## Pieces

| Piece | Where |
| --- | --- |
| Daemon | `/usr/share/grokbot/cypher/cypherd.py`, user unit `cypherd.service` (enabled for every user, `MemoryMax=128M`) |
| Locked limits | `/etc/grokbot/cypher-limits.json` (root-owned; cypherd re-reads it each tick and exits with 78 if it is missing, invalid or writable by others) |
| Seed persona | `/usr/share/grokbot/cypher/persona.md` (a copy in `~/.config/cypher/persona.md` wins) |
| Proxy token | `/etc/grokbot/cypher-brain-token` (root:grokbot 0640), saved with `sudo grokbot-set-cypher-token < file`; never in the image |
| CLI | `grokbot-cypher status / journal -n N / mute / unmute / pause MIN / resume / stop / start / memories / prefs / ntfy-test / requests` |
| Journal | `~/.local/share/cypher/journal/YYYY-MM-DD.jsonl` (0600) |
| State | `~/.local/state/cypher/drives.json` |
| Switches | `~/.config/cypher/KILL` (stop and stay off), `muted` (no on-screen notes), `pause_until` |

## v1 actions

`none`, `journal_thought` (280 chars, 20 an hour), `show_note` (120 chars, 3 an hour, 12 a day; never when muted, in Do Not Disturb, in quiet hours, or when Zack is away), `set_avatar_color` (novad's color list, 2 an hour). Anything else the model proposes is rejected, journaled with the reason, and becomes `none`.

## Quiet hours

`quiet_hours` in the limits file is keyed by the night it starts on: `{"default": ["23:00", "06:00"], "nights": {"fri": null, "sat": null}}` means 11 PM to 6 AM on Sunday through Thursday nights and none on Friday and Saturday nights. A plain `["23:00", "06:00"]` still means every night. To change it without a rebuild, edit `/etc/grokbot/cypher-limits.json` with sudo; cypherd re-reads it on the next tick (an invalid file stops cypherd with exit 78 rather than running unchecked). Once edited on the device, ostree keeps the local copy over later image defaults.

## Brain

1. Alpha's llama-server (Qwen3-VL 8B) through `cypher-brain-proxy` on Alpha port 8090 (LAN first, then Tailscale; token, one request at a time, text only, 150-token answers, 300 for the nightly sleep). The proxy answers busy while llama-server is processing anything, for 30 s after the camera gate logs a decision, and in gaming mode, so the cameras always go first. Its code lives on Alpha in `~/nova-projects/cypher/proxy`.
2. If Alpha is busy or unreachable: the deck's own Qwen2.5 3B Q4 (`cypher-llm.service`, a podman quadlet on the official llama.cpp server image pinned by digest, 127.0.0.1:8081 only, read-only, no capabilities, 3 GB and 3 CPUs, nice 15; Fedora's generic llama-cpp build was 3x slower on the Pi 5). The 2 GB model is not in the image; `cypher-llm-fetch.service` downloads it once into `/var/lib/cypher-llm/models` and checks a pinned sha256.
3. Then hosted Grok (`grok-4.20-0309-non-reasoning`) with the xAI key in `/etc/grokbot/xai_key`, capped at $0.50 a day (worst case checked before each call).
4. Otherwise the tick is `none`. Gaming mode or an unreachable Alpha backs off for 5 minutes; a busy camera model does not.

## Phase 2

**Failover (deck dark -> Alpha).** One mind lease lives in the proxy on Alpha (`~/.local/share/cypher-sync`). The deck always wins it. `cypherd-alpha` (the same cypherd.py with `CYPHER_HOST=alpha`, a user service on Alpha) takes it only when cypherd here stopped cleanly (reboot, shutdown, `systemctl --user stop`) or the deck went dark: the lease was not renewed for 180 s and neither deck address (`failover.deck_addrs`) answers. The kill switch (`grokbot-cypher stop`) parks the lease: nobody takes over until the deck starts again. Writes are fenced by epoch, so exactly one mind saves state. Every tick the holder pushes drives, recent actions, memories, preference notes and its journal to Alpha; when the deck comes back it takes the lease (Alpha's next renew is refused), adopts Alpha's state and merges Alpha's journal entries into its own. On Alpha, Cypher only journals (no screen to show notes on, no hosted key, no local model) and uses the deck's synced limits.

**Camera feed (read-only).** `cypher-camfeed` on Alpha tails the eufy gate, vision reviewer, shadow model and cloud-alert logs and writes allowlisted fields only: time, camera, kind, alerted, source, event id, and family first names from `~/.config/cypher-camfeed/family_names`. No descriptions, clothing, vehicles, reasons, scores, paths or images. cypherd fetches new events from the proxy (`GET /camera/events`) each tick, re-checks every field, nudges drives (family lowers social need, a stranger raises curiosity and focus) and journals them. On a tick with camera events the validator allows only `journal_thought` or `none`, and any action named like a camera, light, lock, door, alarm, PTZ or recording control is refused (the limits file cannot even declare one).

**Nightly sleep.** At 4 AM (`sleep.at`) the active mind condenses yesterday's journal: stats plus the day's thoughts go to the brain, which may return up to 3 memories (140 chars), add up to 2 and drop up to 2 preference notes (max 8 notes, 120 chars, no URLs), and nudge drive drift by at most 0.02 per hour per night (still clamped to the locked bounds). Without a brain it keeps a stats memory. Every preference change is a numbered version in `~/.config/cypher/prefs/` (last 30 kept); `grokbot-cypher prefs` lists them, `grokbot-cypher prefs rollback N` restores one, `grokbot-cypher sleep-now` condenses today at the next tick, `grokbot-cypher memories` shows what Cypher remembers. Memories and notes go into the tick prompt.

## Phase 2.1 (Nov 15 2026)

**Honest manifest.** Each tick the manifest offers only actions that would pass right now: anything at its hourly or daily cap is left out, `show_note` is left out while muted, in Do Not Disturb, in quiet hours or with Zack away, and the validator refuses with the same words. A refused choice shows in "your last actions" as e.g. `set_avatar_color gray (refused: hourly cap)` instead of vanishing. `set_avatar_color` is only allowed when the mood label changed since the last color change, and never to the color it already has; it now relieves boredom by only 0.02, so it is no longer the default outlet.

**Honest camera lines.** A gate "pass" is only the detector's guess, so `cypher-camfeed` holds it until the Eufy routine's verdict for that snapshot folder: quiet.log `no-alert` becomes kind `nothing` (with a reason built only from fixed phrases such as "camera pan, parked cars only") and cypherd never reacts to it; quiet.log `family:` becomes `family` with first names; cloud-alerts.txt becomes `alert`. With no verdict after 10 minutes it goes out as `unconfirmed` with the detector's guess, and the prompt tells Cypher not to guess who it was or invent doors opening. First names only travel on family verdicts. Shadow-model results only sharpen the guess.

**Touch retry.** `grokbot-touch-retry.service` (oneshot at boot) re-binds the Goodix touch controller (any I2C device named goodix, default 11-005d) up to 5 times if it missed its boot probe, logs to the journal and never fails boot.

## Phase 3

All capped in the limits file; deck only unless noted. House, camera and light controls stay impossible.

- `message_zack`: a short ntfy.sh push to Zack's phone. Max 200 chars, 1 an hour, 3 a day, never in quiet hours (none on Friday and Saturday nights). The topic is a secret made on the device with `sudo grokbot-set-cypher-ntfy` (`/etc/grokbot/cypher-ntfy-topic`, root:grokbot 0640; never in the image, the logs or the journal). Without that file the action is simply not offered. `grokbot-cypher ntfy-test` sends one test message.
- `glance_screen`: one low-res grim screenshot (half size, JPEG) of the deck's own screen, sent only to `POST /v1/vision/describe` on Alpha's proxy, where Qwen3-VL describes it with a fixed prompt in at most 40 words. The file is deleted right after reading; the proxy never writes, logs or forwards it. Never the hosted backup. Only while Zack is at the screen and never on a window whose title looks private (passwords, banking, sign-in). 3 an hour, 12 a day.
- `look_up`: a Wikipedia summary (`en.wikipedia.org` only, https, no redirects). 2 an hour, 6 a day. Also on the Alpha standby.
- `request_account`: ask Zack for an account on a named service (`service` max 40 chars, `why` max 160). 1 a day, 2 a week, never in quiet hours, deck only. Writes a journal entry and appends a pending line to `~/.local/state/cypher/account-requests.jsonl`, then sends one ntfy message ("Cypher asks for an account: <service> - <why>. Reply to Nova to approve."). That ping uses the same topic file as `message_zack` but does **not** count against `message_zack`'s hourly or daily caps. If ntfy fails, the pending entry is kept. Cypher cannot sign up, hold a password, read or send mail, or share its address (`s4j6vbnk+cypher@mail.grokbot.com`, a tagged address on Nova's inbox; the address is in the persona so Cypher knows it exists, but cypherd never puts it in a journal line, an ntfy body or the request file). Requests whose service or why mention a password, a house or camera word, a URL with credentials, or the address itself are refused. Nova creates accounts only after Zack approves. `grokbot-cypher requests` lists them; `grokbot-cypher requests resolve N approved|denied` marks one (for Nova, over sudo/ssh).

What glances and look-ups find goes into the journal (`found`), the next few prompts ("you recently found out") and the nightly sleep.

**Pino.** pinos.world has no documented API for visitors or agents. Its web app talks to undocumented internal endpoints, and anything beyond the front page needs connecting an account by email. There is no `visit_pino` action. Cypher can use `request_account` to ask Zack first; Nova would create the account only after he approves.

## Not yet

Ask Nova, speaking, self-improvement, the cyberpunk theme, visiting Pino. See the design page for the plan.

## Tests

`python3 tests/cypher/test_cypherd.py`, `test_cypherd_phase2.py` and `test_cypherd_phase3.py` (run by `tests/test-rpi5-nova.sh`), and `bash tests/test-rpi5-touch-retry.sh`. The proxy, lease store, camfeed and a two-process failover test (`test_failover_e2e.py`) live with the Alpha code in `~/nova-projects/cypher/tests`.
