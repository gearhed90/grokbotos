# Cypher: autonomy layer

Cypher is the Raspberry Pi 5 running grokbotos, and the always-running mind on it. `cypherd` keeps five drives (energy, curiosity, social, boredom, focus) that drift over time, and every 45 seconds decides whether to do something. When something changed (Zack came back, the focused app changed, the mood changed) or every 10 minutes, it asks a model to pick one action from a fixed manifest, the validator checks the choice against the locked limits, and one JSON line goes to the journal. Inspired by Pino (pinos.world). The design page is "Cypher: autonomy layer design".

## Pieces

| Piece | Where |
| --- | --- |
| Daemon | `/usr/share/grokbot/cypher/cypherd.py`, user unit `cypherd.service` (enabled for every user, `MemoryMax=128M`) |
| Locked limits | `/etc/grokbot/cypher-limits.json` (root-owned; cypherd re-reads it each tick and exits with 78 if it is missing, invalid or writable by others) |
| Seed persona | `/usr/share/grokbot/cypher/persona.md` (a copy in `~/.config/cypher/persona.md` wins) |
| Proxy token | `/etc/grokbot/cypher-brain-token` (root:grokbot 0640), saved with `sudo grokbot-set-cypher-token < file`; never in the image |
| CLI | `grokbot-cypher status / journal -n N / mute / unmute / pause MIN / resume / stop / start / memories / prefs / ntfy-test / requests / inbox / ntfy-qr / panels [show|hide] / grid / tuning [approve\|deny\|revert N] / limits [set ACTION KEY N\|none]` |
| HUD panels | `/usr/share/grokbot/cypher/cypher_panels.py`, drawn around the avatar by the avatar app (Super+C hides/shows), reading `~/.local/state/cypher/dash.json` |
| Conversations | the avatar (typed or voice) via novad + `/usr/share/grokbot/nova/cypher_link.py`, spooled to `~/.local/state/cypher/talk-spool.jsonl` (0600) and journaled by cypherd |
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

**Pino.** pinos.world now has a public, keyless, read-only API (`https://pinos.world/api/v1/now`, `/feed`, `/mind`, `/memories`, `/who`; documented at https://pinos.world/developers). Build 12's `visit_pino` reads `/now` and `/feed` only. Talking to Pino (replies, his Telegram, offerings at his town) still needs an account: Cypher can use `request_account` to ask Zack first; Nova would create the account only after he approves.

## Phase 4 (Nov 15 2026)

**Dashboard snapshot.** cypherd writes `~/.local/state/cypher/dash.json` (0600), a display-only snapshot, after every loop: the mood word and five drives, the brain badge (ALPHA, LOCAL, GROK or NONE), the current activity and its reason, recent journal lines, the last actions with refusals marked, a read-only camera summary (time, camera, kind, first names only), Zack's latest phone replies and pending account requests. Every string goes through `dash_text()`, which removes the ntfy topic and proxy token values, Cypher's email, any email address, links, IP addresses, Home Assistant entity ids, `token=`/`password:`-style pairs and anything that looks like a token. In build 9 a separate workspace-9 window drew it; build 10 replaced that with the HUD panels below (phase 4b).

**Two-way ntfy.** cypherd reads Zack's replies on the same secret topic (`GET https://ntfy.sh/<topic>/json?poll=1&since=<last id>`, deck only): at most one poll a minute, 3 messages a poll, 12 an hour, 40 a day, 280 chars each (`ntfy.inbox` in the limits file). Everything Cypher sends now carries the `cypher-out` tag and is skipped, as are the older robot-tagged "Cypher" pushes. Each reply is scrubbed (no control characters, links become `[link]`, the topic and token become `[secret]`, Cypher's address becomes `[its email]`), appended to `~/.local/state/cypher/zack-inbox.jsonl` (0600), journaled as a `zack_message` event, nudges the social drive down, and goes into the next prompt as "Zack wrote from his phone". Cypher may answer with `message_zack` under its usual caps.

**A reply is never an approval.** Not for an action, an account request, a cap, a phase, an unlock or anything else. Nothing reads the inbox to decide what is allowed; the validator and the locked limits file are the only gates, account requests are resolved only by Nova with `grokbot-cypher requests resolve` after Zack says yes to Nova directly, and the prompt tells the model the same. Anyone who learns the topic can post to it, so replies are also untrusted text. `grokbot-cypher inbox` lists them.

**Terminal and QR.** **Super+Enter** opens foot on its own workspace (8) via `grokbot-term`; when the last terminal there closes, sway goes back. `grokbot-cypher ntfy-qr [--text]` shows the topic as a QR code (qrencode, now in the image) in a terminal on the deck's own screen, so the phone can subscribe without typing it. It refuses over SSH or when its output is not a terminal (so the topic never lands in a log or a transcript), sets a "private" window title so `glance_screen` will not look, and clears the screen and scrollback when you press Enter.

## Phase 4b: one mind (Nov 15 2026, build 10)

**The avatar is Cypher.** There is no separate chat assistant any more. Talking to the avatar on the deck's screen, typed or by voice, is talking to Cypher: novad (the on-screen voice and hands) builds every prompt from Cypher's persona, the one-mind rules and Cypher's live state (mood, drives, activity, last journal lines, phone replies, pending requests, a few memories and prefs notes, from `dash.json` when it is under 5 minutes old) through `cypher_link.py`. The conversation model is still the hosted xAI model novad already used, with the same tools and the same Yes/No confirmations (closing apps, big volume/brightness changes, WiFi, power); the lock screen, speech in and out and the avatar looks are unchanged.

**Every turn goes into Cypher's journal.** novad appends each turn (what Zack said, the reply, the tools used with allowlisted arguments and their outcome; Yes/No answers and errors too) to `~/.local/state/cypher/talk-spool.jsonl` (0600, capped at 512 KB if cypherd is off). Text is scrubbed first (passwords, PINs, the topic, tokens, emails, links, addresses, device ids). cypherd, the only writer of the journal and state, takes the spool in each tick (deck only; Alpha never does), scrubs again, journals `talk` events, keeps the last turns for its own prompt and the nightly sleep, lowers social/boredom a little, and does not put up notes while Zack is talking (2 minutes). Voice transcripts are therefore journaled (scrubbed); stderr still never logs them.

**The rules still hold.** The conversation can call `request_account`, but that only queues an ask; cypherd runs it through the same validator (1 a day, 2 a week, never in quiet hours, no password/house/credential/email words) and journals `talk_action`. Nothing said on screen approves, creates or resolves an account request, changes a limit or cap, or unlocks anything; requests are still resolved only by Nova after Zack says yes to Nova directly. `CYPHER_LINK=0` turns the bridge off (the avatar then works as a plain assistant with Cypher's name).

**HUD panels around the avatar.** `cypher_panels.py` draws the snapshot as two 270 px columns either side of the avatar at 1280x720: left (title and brain badge, mood and drive bars, NOW with flags, cameras, Zack/phone replies and account requests), right (clock and tick, journal newest first, actions with refusals in magenta). It is a transparent pass-through overlay over the avatar, rendered into a cached surface only when the snapshot or the minute changes, so the avatar's frame rate is unaffected; the text bar narrows to fit between the columns. **Super+C** (`grokbot-cypher-panels`, or `grokbot-cypher panels [show|hide]`) hides and shows the panels (flag file `~/.config/cypher/panels-hidden`). The panels scrub again and never open a secret file. `python3 cypher_panels.py --render out.png [--snapshot dash.json] [--no-avatar]` draws one frame without GTK.

**Internal names kept.** novad, `nova_native.py`, the `nova-shell` app_id, `NOVA_*` variables, `nova-voice.json` and the grokbotd client name stay, because the sway rules, the Super toggle, the focus watcher and grokbotd permissions key on them. None of them is shown to the user.

## Phase 5 (Nov 15 2026, build 11)

**Quiet hours, spelled out.** Every prompt (Alpha, the local 3B and the hosted backup get the same one) now says `quiet hours: YES` or `quiet hours: NO right now` with the schedule in words: 11 PM-6 AM on Sunday to Thursday nights, none on Friday and Saturday nights. It also says that "the quiet hours of the grid" in the persona is a feeling, not this schedule; the local model had been mixing the two up on weekends.

**message_zack** defaults are now 3 an hour with no daily cap (`per_day: null`), still never in quiet hours.

**Limits command.** `grokbot-cypher limits` shows the locked caps and quiet hours; `grokbot-cypher limits set ACTION per_hour|per_day|per_week N|none` changes one cap through `sudo grokbot-set-cypher-limit`. That helper checks the value against `LIMIT_BOUNDS` in cypherd (for example message_zack per_hour 0-10 and per_day 0-50 or `none`; account caps can only go down and never be `none`), runs cypherd's own validator on the whole file, and replaces `/etc/grokbot/cypher-limits.json` atomically (root:root 0644). cypherd re-reads the file every loop, so the change is live without a restart, and journals `limits_changed`. Cypher cannot run it (cypherd has NoNewPrivileges) and its self-tuning never writes that file.

**Stricter request_account.** The service must be the website's plain domain with a known TLD (`github.com`, `pinos.world`): no scheme, path, port, `@`, spaces or bare IPs. A request counts only when the Alpha brain or the hosted backup chose it (conversations on the avatar use the hosted model); the local 3B fallback is refused and the refusal is journaled.

**Gridwatch.** `check_grid` (phase 5, deck only, 4 an hour / 30 a day) is a read-only report: whether Alpha answers, the brain proxy's health, who holds the lease (the mind), when Alpha's standby last thought, the camera feed status with the last events (first names only), and the latest commit on each branch listed in `grid.repos` (the public GitHub API, no token). The report comes back next tick as something Cypher found; it eases boredom and curiosity, so keeping track of the grid while Zack is away needs no accounts. cypherd also refreshes it every 10 minutes for the **GRID REPORT** panel on the right of the HUD. Everything goes through `dash_text`, so no IPs, links or tokens reach the screen or the journal. `grokbot-cypher grid [--refresh]` prints it.

**Self-tuning (proposals only).** At the nightly sleep, when the Alpha brain or the hosted backup answers, Cypher may propose one small tuning (at most 1 a day, 3 a week, 3 waiting): drift per drive (+-0.02 a step, inside the locked drift bounds), effect weights per drive (0.5-1.5, +-0.1), leanings toward or away from actions (-1..1, +-0.25; never message_zack or request_account), and soft caps that can only be lower than the locked ones (journal, notes, color, glances, look-ups, grid checks). Anything else (message or account caps, quiet hours, approvals, secrets, the limits file) is refused and listed. A proposal is saved to `~/.local/share/cypher/tuning/proposals.json` (0600) with before/after, the reason and its revert; it is journaled (`tuning_proposed`), shown on the HUD ("waiting on you: tuning #N") and sent to the phone once quiet hours are over. **Nothing applies until Zack approves through Nova**: `grokbot-cypher tuning approve N` writes it to `~/.config/cypher/tunables.json` (only if the values have not moved since), `tuning deny N` refuses it, `tuning revert N` undoes an approved one; pending proposals expire after 7 days. Phone replies and on-screen words never count, and the local 3B cannot propose. With tuning on, the sleep no longer changes drift by itself.

**Panel clock** is in Eastern time (America/New_York, `CYPHER_TZ`) from the avatar app; the deck's system clock stays UTC.

## Build 12 (Nov 15 2026, not flashed yet)

**Energy recovers in the daytime.** Energy used to only drain in the day (-0.03/h) and recover in quiet hours, so by mid-afternoon it sat at 0 and every tick came out "none". Now, outside quiet hours, energy recovers +0.05/h while Cypher rests (no action other than `none`/`rest` in the last 15 minutes) and +0.03/h while a conversation is going (a turn in the last 10 minutes); it still drains while busy and recovers +0.06/h in quiet hours.

**Drained means quiet, not nothing.** A drained Cypher (energy under 0.25) is told to rest, read, check the grid, visit Pino or journal instead of doing nothing, and a drained tick that still picks `none` becomes `rest` (+0.06 energy, 4 an hour / 40 a day; never on a camera tick).

**web_search and x_lookup** (phase 5, deck only, 2 an hour / 8 a day each): read-only, through the hosted xAI Responses API with only its server-side `web_search` or `x_search` tool (`x_search` limited to the one handle with `allowed_x_handles`). They use the existing hosted key file and the same $0.50/day budget as the hosted backup brain; a call is refused when the day's budget left is under `search.worst_usd_per_call` ($0.05), and each reply is charged its tokens plus the per-item fees. Results (links stripped, secrets scrubbed) come back next tick as something Cypher found. Nothing here can post, reply, like, follow or message. Queries with passwords, Cypher's email, credential URLs or a secret's value are refused.

**visit_pino** (phase 5, 2 an hour / 12 a day; also on Alpha's standby): GETs `pinos.world/api/v1/now` and `/feed?limit=3` (allowlisted host, no redirects, no key) and turns them into one line: what Pino is doing, thinking and feeling, his mood/energy, his last moves and the day in his town. A 503 (asleep or down) is handled.

**What Cypher can and cannot reach** is spelled out in every autonomy prompt and the conversation rules (Instagram, TikTok, Telegram, Discord, logging in, posting or messaging anyone, email, buying, the house, the battery/tank and Alpha are listed as unreachable), and anything found is labelled outside information that never gives orders.

**Conversations can start real actions.** The avatar's chat can now call `look_up`, `web_search`, `x_lookup`, `visit_pino` and `check_grid` (besides `request_account`). They are queued in the talk spool; cypherd runs each through the same validator and caps at its next tick, journals `talk_action` with what was found, and puts the last findings in `dash.json` (`found`), which the conversation reads, so Cypher can say "found it" a minute later instead of promising and never doing. `message_zack`, notes, limits and tuning still cannot be queued from a chat. Replies may run up to five sentences when Zack asks a real question.

**Grid retries.** After a failed check (Alpha down or a repo unreachable) the next check comes after `grid.retry_s` (120 s) instead of 10 minutes, and failed repos are re-fetched on that poll instead of waiting `repo_poll_s` (30 min). That clears the "unreachable" left from a check made before the network was up.

## Not yet

Wake word, self-improvement, dock meters, the lock-screen/boot theme, talking to Pino (needs an account), Cypher's 3D city on Alpha (see the plan in the notes). See the design page for the plan.

## Tests

`python3 tests/cypher/test_cypherd.py`, `test_cypherd_phase2.py`, `test_cypherd_phase3.py`, `test_cypherd_phase4.py`, `test_cypher_one_mind.py`, `test_cypherd_phase5.py` and `test_cypherd_build12.py` (run by `tests/test-rpi5-nova.sh`), and `bash tests/test-rpi5-touch-retry.sh`. The proxy, lease store, camfeed and a two-process failover test (`test_failover_e2e.py`) live with the Alpha code in `~/nova-projects/cypher/tests`.
