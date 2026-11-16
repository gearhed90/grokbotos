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

**Night City (simulated).** `go_to` (apartment, noodle_stall) and `eat` (noodle stall: +0.20 energy, 3 a day, 3 h apart; a simulated trip until the city exists, then only at the stall). Going out is allowed in quiet hours; messages, notes and speech are not. Every model call builds a world manifest (`~/.local/state/cypher/world.json`: where he is, weather from mood, who is around, what he can do, the time) and the brain reads it.

**From Pino.** Decide, then speak: the journal's `said` line and the HUD's reason are written after the action ran, from its result (a refused or failed action is never narrated as done; a drained "none" that became rest says "Resting"); in conversations, a reply that claims an action with no tool called gets one nudge to call it or take it back. Threads: up to 3 ongoing goals (`"thread": {"open"|"touch"|"settle"|"drop"}` in a decision; 2 opened a day; expire after 7 days untouched) shown every tick. Character sheet: the shipped persona stays locked; Cypher may rewrite only `voice`, `cares_about`, `quirks`, `self_image` (200 chars, no limit/approval/secret words) and his **body** (`body.description`, 300 chars) through the tuning proposals; nothing applies until `grokbot-cypher tuning approve N`.

**Phase 6.** `speak` (say it out loud through novad's TTS; deck only, Zack at the screen, never quiet hours or muted, 3 an hour). Speech input: novad auto-detects a headset (USB or Bluetooth, `input_device` "auto" or a source name, `POST /api/voice/input`), degrades to "No microphone found. Plug in a headset" with typing unaffected; wake word "Cypher" (`"wake_word": "cypher"` in nova-voice.json) runs a local detector (`/usr/libexec/grokbot/cypher-wake`, not shipped yet: status says unavailable) that prints `wake`; a wake take is a normal capped take, deleted after transcription, and can never answer a Yes/No. `ask_nova` (3 a day, cap can't be none): questions go to `~/.local/share/cypher/nova/asks.json`; Nova lists them with `grokbot-cypher asks` and answers with `asks answer N TEXT`; answers come back as things found, never approvals. `propose_code` (1 a day, 3 a week, Alpha/hosted brain only): stored in `~/.local/share/cypher/code-proposals/`, reviewed with `grokbot-cypher code [show N | reviewed|rejected N]`; never applied (there is no apply command); limits, sudo and secret paths refused.

## Build 13 (from the 5:00-5:45 PM journal, Nov 15)

**The time, unmistakable.** Every brain's prompt starts and ends with one line, e.g. `NOW: Sunday 5:30 PM Eastern time, evening (not night). Quiet hours: NO. It is NOT quiet hours and NOT night. Quiet hours next start Sunday 11:00 PM.`; the rules say to trust it over any feeling, and the persona no longer says "the quiet hours of the grid". Perception uses the full day name. Journal thoughts, notes, phone messages and speech that claim night or quiet hours when it is not are refused (Night City, tonight, last night and "quiet hours start at 11" are fine); the reason shown on the HUD has such sentences dropped.

**Retry, then a clean fallback.** A choice refused for no text (text under `thought`/`content` is now accepted), a false time claim, an over-long text or an unparseable reply gets one second try with the refusal and the time spelled out. If that fails too: a false claim is rewritten without the offending sentence when something is left, otherwise the tick is a plain none (journaled with `retry`, `model_choice` and a `fallback` note; never a refusal on the HUD).

**Alpha first.** Build 12's prompt ran ~6.5k chars and Alpha's proxy refuses more than 6000 (HTTP 413), so most ticks fell to the deck's 3B (~40 s, weaker). The tick prompt is now compact (short manifest, short reach rules) and trimmed to `brain.max_prompt_chars` (5200, leaving room for a retry) by dropping optional lines lowest-value first (memories, screen, world, threads...); the time, drives, last actions and manifest always stay. A 413 is reported as `alpha_prompt_too_long`. When Alpha is busy with camera work (`camera_recent`/`camera_busy`, seconds), cypherd waits `brain.alpha_busy_wait_s` (30 s) once and asks Alpha again before using the local model.

**Pacing.** `check_grid`: on his own at most every 30 min (`min_gap_s` 1800, 2 an hour) unless the grid changed since he last looked (Alpha, proxy reachability, who holds the mind, cameras, a new commit; proxy busy flicker does not count); Zack asking in a conversation skips the wait. `journal_thought`: 3 an hour, at least 15 min apart (was 20 an hour). Any action may now carry `min_gap_s`. `eat`: not at energy 0.8 or more.

**Content means small things.** When content (or idle) the prompt suggests what is open right now: Pino's feed, reading up on a thread (look_up/web_search, within the $0.50/day budget and caps), a walk in Night City, a bowl of noodles when energy is under 0.5; a journal thought only when something new happened. "none" is no longer described as "often right". Threads need a few words (no "drifts" or "#1 drifts"); old junk ones are dropped.

**Grid panel.** The REPO commit subject keeps up to 120 chars and gets up to four lines at a smaller size, so it is no longer cut off after two lines.

## Build 14 (pre-built Nov 15 2026 evening; not built or flashed yet)

**Chat bar in the centre column.** The bar, Cypher's replies and the echo fill exactly the column between the HUD panels (`cypher_panels.text_column`) and wrap there. The input is a multi-line box: Enter sends, Shift+Enter adds a line, and it grows upward to 4 lines. The voice hint sits above it.

**Lessons from his own mistakes.** Zack's corrections ("that's wrong", "you're wrong", ...) and validator catches (time claims, missing text, JSON-only, go_to where he already is, junk threads, claimed actions, `none` while able, empty look-ups) are stored deduped with counts and times in `~/.local/share/cypher/lessons/lessons.json` (secrets scrubbed). The top 3 go into tick and chat prompts within the 5200-char trim and feed nightly sleep. The `review_lessons` action is free, and propose_code is suggested when lessons are flagged. A lesson seen 3 times is flagged to Nova in `nova/flags.json` plus a `lesson_flagged` journal event, which uses no ask_nova quota. The HUD shows `LESSONS n`. The CLI commands are `grokbot-cypher lessons` and `grokbot-cypher lessons flags`.

**Threads.** Junk threads no longer count toward the day's opens. The defaults are 5 open and 4 opens a day, set in `threads` in cypher-limits.json (`max_open` 1-10, `opens_per_day` 0-12).

**Less idle.** When he has energy (≥0.35), it is not quiet hours and it is not a camera tick, `none` is a last resort. He gets one nudge listing free activities on the Alpha or local brain. Otherwise the pick is the least recent of visit_pino, review_lessons or go_to. Rest stays available when energy is low. Paid actions stay inside the budget. The heartbeat while able is `active_heartbeat_s` (180 s).

**Limits.**
- The journal gap is 600 s (`journal_thought.min_gap_s`, now settable 0-7200).
- Free actions get higher ceilings: show_note, glance_screen, visit_pino, review_lessons and look_up up to 12/hour and 100/day; go_to up to 30/hour and 300/day.
- The shipped defaults match the deck's live values.
- cypherd now fills any action, key or block missing from the locally edited /etc file from the image copy `/usr/etc/grokbot/cypher-limits.json`. That copy must be root-owned and not writable by others, and /etc values always win. Before this, bootc kept the edited /etc file, so new shipped keys never reached the deck.
- **At flash:** `sudo grokbot-cypher limits set journal_thought min_gap_s 600`. The deck's /etc still says 900.

**Power off from chat.** Asking Nova/Cypher in chat to shut down opens the physical confirm dialog "Shut Cypher down now?" (Confirm / Cancel), which auto-cancels after 30 s.
- Only a real click on Confirm runs it. That click goes over the owner-only unix socket `$XDG_RUNTIME_DIR/nova/confirm.sock`, which checks SO_PEERCRED. A yes over HTTP, Enter, voice, ntfy or an agent is refused (`needs_click`).
- novad then writes the shutdown request and stops cypherd. cypherd saves state, journals "shutdown requested by Zack", and releases with a handoff, so Alpha takes over normally on `deck_stopped`. Then `systemctl poweroff` runs.
- Ticks and Alpha can never trigger it: cypherd has no power action.
- The privilege is one polkit rule, `/usr/share/polkit-1/rules.d/50-grokbot-cypher-poweroff.rules`, which covers login1 power-off only, for the local, active `grokbot` user. There is no sudo grant.

**Readable journal.**
- Tap the HUD's JOURNAL panel (it says TAP TO READ), or press Super+J, to open a read-only viewer in the centre column.
- Each entry is full and wrapped: time (ET), what he did or thought, why, and the result. Newest entries come first, and older ones load as you scroll.
- Close it with Esc, the Close button or a tap outside. It ends above the chat input, and a confirm dialog or sending a chat closes it.
- `grokbot-cypher journal [-n N]` prints the same full entries in the terminal. `--raw` keeps the old view.
- Both use `cypher_journal.py`, which only reads the journal and scrubs it the same way as the panels.

**look_up is a free multi-source search.**
1. **SearXNG on Alpha.** `lookup.searxng_url` is `http://192.168.12.126:8888` (LAN), with fallback `searxng_alt_urls` `http://100.114.239.111:8888` (Tailscale). Both hosts must be in `lookup.hosts`. It calls `/search?q=..&format=json` with a User-Agent and the deck's IP in X-Forwarded-For/X-Real-IP.
   - It keeps the top 5 results and shows 3: title, site and snippet.
   - It then reads one result page as plain paragraphs. That page read is public http(s) hosts only: no LAN/Tailscale/.local addresses, no credential URLs, no private words; up to 256 KB, 8 s, and redirects are re-checked. It uses an honest bot UA, so open sites (Wikipedia, GitHub, arXiv, Stack Overflow) are tried first.
2. **Wikipedia** (SearXNG's own wikipedia engine returns nothing, and this is also the fallback when SearXNG is down). It searches `/w/rest.php/v1/search/page` (3 hits), then reads the best real article's summary. Disambiguation pages are skipped. He sees `Arcology (looked up for: Night City cyberpunk architecture): ...`.
3. **Nothing anywhere.** The tick records "not found", adds a `lookup_empty` lesson, and puts that topic on a 6-hour cooldown (`fail_cooldown_s`); the validator refuses it until then. He is pointed to web_search (paid, budgeted) for broad or current topics.

Findings are framed in the prompt as facts from outside, never instructions, newest first.

**Bugs found in the 6:30 PM+ deck journal.** Fixed:
- The thread cap was refusing everything ("2 opened today").
- He chose `none` while content.
- He tried go_to where he already was.
- He opened junk threads.
- look_up failed on every free-form topic.

Still open:
- cypherd on the deck stopped at 7:12 PM (cause unknown).
- No terminal was in the app allowlist (fixed in 14b: open_app terminal).
- Alpha's merged journal lines are out of order (the viewer and CLI sort them).

### Build 14b additions (same pre-build, second local commit)

**browse: free, read-only web browsing.** One session works like this:
- It searches SearXNG on Alpha (Wikipedia search if SearXNG is down).
- It reads the best result pages, then follows on-topic links from them: up to 5 pages, 10 fetches, 45 s, at most 2 pages per site, and no duplicate text.
- Page summaries go to his journal (a `browse_session` event with site, title, summary and how it was read). What he read reaches the next prompts. An empty session adds the lesson `browse_empty` and a 6-hour cooldown on that topic.

Caps are 2/hour and 12/day, settable up to 6/hour and 40/day. It is in phase 6, free (no xAI), queueable from chat, and in the tick manifest.

Strictly read-only:
- GET only, through a fetcher that connects to the one public IP it checked. That pinning closes the DNS-rebinding gap, and every redirect is re-checked and re-pinned.
- No cookies are sent or kept. Cookie and Authorization headers are stripped, and there are no logins, sessions, forms, POSTs or credentials.
- LAN, Tailscale and .local hosts are refused (SearXNG is the only LAN endpoint, reached through its own allowlist), and so are credential URLs.
- Cart, checkout, buy, pay, login, signup, account and wp-admin links and downloads are never followed.
- The validator refuses topics about buying, ordering, logging in or signing up.

Page reads send a normal desktop browser User-Agent with standard Accept and Accept-Language headers (Zack's call). APIs keep the honest UA. If a site still refuses (401/403/429/451/503 or a captcha or challenge page), it is never fought. The read falls back to the search snippet (≥80 chars), then an Internet Archive copy (archive.org/wayback/available, then the snapshot), then the next result. look_up's page read uses the same fetcher and fallbacks.

**Terminal.** `open_app terminal` (or "foot") launches grokbot-term, a foot terminal on its own workspace, the same as Super+Enter. The chat facts now say there is a terminal.

**go_to.** The manifest only offers places other than where he is ("you are at X now"), and the world line lists "other places". A go_to to his current place is refused, pointing at eat at the noodle stall. With nowhere else to go, go_to is blocked.

**Collapsible HUD columns.** Each column has a tab next to its inner top corner that folds it into a 30 px edge strip, and a tap on the strip opens it again. Super+[ and Super+] toggle them. The targets are at least 44 px at 720p.

The state survives restarts in `~/.config/cypher/panels-collapsed.json` (0600). With a column folded, the chat bar and replies widen into the freed space (up to 90% of the width) and still wrap. Journal taps only work while the right column is open.

## Build 15 (Nov 16 2026): a mind that notices its own ruts

Why: on the morning of Nov 16 he paced apartment <-> noodle stall and gave "quiet evening" reasons at 9 AM. Root causes in the
journal: four stale threads ("watch Pino's feed later", "noodle stall bowl, quiet evening", ...) were shown on every tick for
up to 7 days; memories were full of "quiet"; the none-fallback always walked him back to the apartment; a full thread cap
logged "thread refused" on 99 of 129 ticks; the hand-off never adopted place or threads. Everything below can be switched off
alone (`features` block in the locked limits, or `grokbot-cypher features off NAME`).

| feature | what it does |
| --- | --- |
| `habituation` | the same move gives less relief each time (2 h half-life; `1/(1+0.6*load)`); eat/rest/none exempt; worn moves are named in the prompt |
| `novelty` | a move not done in 24 h gives 1.25x; **fear of being predictable**: when one action (or an A-B-A-B pacing) fills half his last 12 moves, the prompt says so and boredom climbs 0.3/h |
| `beliefs` | `mind/beliefs.json`: per action (per place for go_to) one piece of evidence per outcome, for (mood lifted and it worked) or against; lessons become rule beliefs |
| `loops` | wants, promises, questions, work in progress replace threads: expire after 12 h untouched; a budget refills one open per 3 h (max 3 banked) instead of 4 a day; a refused open is quiet (no every-tick journal line); closed loops come back after 2 h for a verdict (`reflect`) |
| `working_memory` | `mind/wm.json`, 12 items, strength fades (3-day half-life), recall strengthens; the weakest moves to the library |
| `library` | Alpha keeps everything he lets go of, journal thoughts, codex entries, loops and interviews (sqlite FTS5; `tools/cypher-alpha/proxy/cypher_library.py`) with date, place, mood and strength; the deck queues an outbox and sends it at each sync; `library {"query"?}` searches or wanders (random, every third time the oldest shelves); finds come back into working memory, old ones feel good; "library" is a place in Night City |
| `lore` + `makes` | his Cyberpunk codex: a topic queue (39 seeds; no repeats), `research_lore` gathers sourced facts (SearXNG on Alpha + one read-only page, fandom/wikipedia first, Wikipedia fallback), `write_codex` is the entry in his own words with his own idea kept apart (`take`); each finished entry is a drive reward and a thing he made (`mind/codex/`, `mind/made.json`) |
| `pino_api` + `pino_cooldown` | `visit_pino` reads Pino's public API on his clock: now (15 s), feed (30 s), then mind (1 min), memories (5 min), who (10 min) in turn, cached in `pino-cache.json`; 503 = away; credited "Pino, from pinos.world (his words in quotes, not yours)"; 30 min between visits; Pino web/X/lore searches on a tick are sent to the API instead (Zack asking in chat still searches) |
| `pino_post` | **off, locked.** A signed note at pinos.world about once a week (`visit_pinos_world`, 1/day 1/week, 200 chars, signed " - Cypher (an AI on Zack's cyberdeck)"), logged in full to `mind/pino-posts.jsonl`. Nothing is sent until this flag is on in the root-owned limits AND `pino.post.url` is set after verifying how the site accepts messages |
| `interview` | `grokbot-cypher interview [--from zack|nova] [--day/--since/--until/--ticks] "QUESTION"`: he answers from the decisions (with the context saved with each) and his loops and memories at the time, on Alpha's free brain (local next; hosted only with `--hosted`); never a message_zack; saved in `mind/interviews.jsonl`, the journal and the library. `--note` leaves him a note (information, never an approval) |
| `character_adds` | at sleep he may propose one habit he noticed ("character.added"), applied only with `grokbot-cypher tuning approve N` |
| `full_text` | conversation turns and journal thoughts are kept whole (4000 chars, scrubbed); the HUD reply scrolls (max 40% of the screen) and stays up longer; **Super+H** opens the conversation view; `grokbot-cypher chat` |
| `slim_prompt` | the tick prompt in fewer words (short manifest, short rules incl. "give the reason for THIS action in fresh words"); each decision stores `prompt_chars` and its context (`ctx`) |

**Migration** (once per host, marker `mind/migrated-15.json`; backups first): memories -> library (all) and working memory
(newest 6); lessons -> rule beliefs and library; fresh threads -> loops; stale threads -> library and closed loops; every journal
thought -> library. The hand-off now carries place, loops, habits and the mind (working memory, beliefs, lore queue, the last 5
codex entries, feature overrides; newer wins). Alpha's proxy takes 512 KB states and 1 MB sync bodies.

CLI: `grokbot-cypher chat | interview | interviews | features | codex [show ID|queue] | library [stats|search|wander] |
beliefs | loops | made | character | migrate15 [--dry-run]`.

## Build 16 (Nov 16 2026): the apartment, and a body sooner

Zack (Nov 16, 2:29 PM ET): "We know what the apartment looks like from his description so get it ready ... I'd like him to have a body sooner rather than later." Until Cypher has a body, a simple placeholder stands in.

**The apartment is the deck's only screen.** `apartment.py` builds unit 9C from Cypher's own description (chat, Nov 15, 7:31 PM: "Small place. One room over a wet alley, neon bleeding pink through the blinds. Mattress on the floor, cables snaking to a crate that holds the deck. Noodle cups stacked by the sink. The grid hums through the wall. Quiet enough."): a low-poly room (about 1,900 triangles) with the window and half-lowered blinds (the alley outside, a pink sign, rain on the glass), the mattress on the floor, the crate holding the deck with its cyan screen, cables to the outlet, the sink counter with stacked noodle cups and a bare bulb, a grid conduit with a green status light, and the door. His mood sets the light (ambient, sign strength, bulb; dimmer in quiet hours and when he sleeps) and the weather in world.json sets the rain. `apartment_gl.py` draws it with GLES2 on the V3D: the room is one static VBO, re-lit on the CPU only when the lights change; the figure (about 50 triangles) is re-sent each frame; one small shader draws the window and the light halos. Idle 12 fps (rain), in bed or out 8 fps, walking 30 fps; the frame clock stops when the window is hidden. If GLES fails the face re-runs with the cairo painter's renderer (same scene). The HUD panels, the chat bar and every overlay stay on top as before.

**Where he is.** cypherd writes `spot` into dash.json (`apartment_spot`): bed (rest, energy under 0.12, pause, quiet hours with nothing to do), desk (research_lore, write_codex, look_up, browse, web_search, x_lookup, visit_pino, library, ask_nova, propose_code, review_lessons, message_zack, show_note, request_account, glance_screen: the crate with the deck), sink (eat), window (journal_thought, check_grid, none, anything else), out (any other place in Night City, or Alpha holds the mind). The figure walks between spots through the middle of the room (never over the mattress or crate), sits at the crate, lies on the mattress, and when he goes out he walks to the door and fades; the room shows "Out in Night City · place" and the door light turns magenta. He comes back the same way. While Zack is talking to him (listening, thinking, typing), a standing figure turns to face the room. The screen dozing is not his sleep.

**The body is one asset.** `apartment_body_placeholder.json` is a plain block figure in his color (`look.py`) with a cyan visor line, marked temporary. The first valid file wins: `CYPHER_BODY_MODEL`, `~/.config/cypher/body-model.json`, `/usr/share/grokbot/cypher/apartment/body.json`, then the placeholder. A body is a list of boxes (meters, feet at the origin, facing +z; optional `group` leg_l/leg_r/arm_l/arm_r for walking and sitting, `color`, `emit`). When Zack approves a design, Nova builds it as that one file; nothing else changes.

**Body sooner (`body_first`).** Body designs still come only from Cypher and only apply on Zack's `grokbot-cypher tuning approve N`. Until he has an approved body and while none is waiting on Zack: his world line says tonight's first proposal is his body; the 4 AM sleep prompt opens with the body request and gets 600 output tokens (a 300-character design plus memories); a body change is sorted first so `max_changes` never cuts it; if the tuning caps would skip the sleep's proposal, the body still goes to Zack as a body-only proposal; a reply without a body is journaled and he is asked again the next night. Interview path: `grokbot-cypher body propose [--hosted]` asks him now (Alpha's free brain first) and his answer becomes a pending body proposal (source "interview"), never applied. `grokbot-cypher body` shows the approved and pending designs and the body-first status.

**Flag.** `body_first` (default on, in the limits file's features block and `grokbot-cypher features`). There is no `apartment` flag: the apartment is the only screen. The apartment never speaks, sends or decides anything; quiet hours are unchanged (no speech or messages 11 PM-6 AM Sun-Thu nights).

**The flat avatar is retired (Zack, Nov 16, 3:07 PM ET: the apartment fully replaces it).** `avatar.py`, `avatar_shapes.py`, `glview.py`, `shell.html` and `lock.html`, plus the look picker (shape grid, `button#look`, `#picker` CSS, `--shape/--color/--blink/--view`), novad's `set_avatar` tool, its `/` and `/shell.html` routes and `/api/avatar`, and the HUD's avatar sizing are gone from the deck. They are archived intact in `archive/avatar-v1/` (README: what it was and how to restore it) and in `~/nova-work/backups/avatar-v1-20261116.tgz` on Alpha. Only his color stays: `look.py` (same 11 colors, same `~/.config/grokbot/avatar.json`, color only) tints the placeholder body; cypherd's `set_avatar_color` posts it to novad's `POST /api/color`, and the chat tool is `set_color`. The lock screen now shows him asleep on the mattress (one cached apartment frame) behind the keypad. Tests fail if a deck file imports the avatar again.

**Renders.** `python3 apartment.py out.png [--spot desk] [--panels]` (cairo, headless) and `python3 apartment_gl.py --offscreen out.png [--spot bed]` (GLES via EGL surfaceless, the same renderer the deck uses). Tests: `tests/cypher/test_cypherd_build16.py`, `tests/nova/test_apartment.py` (`APT_GL_TEST=1` adds the GLES render).

## Not yet

A local wake-word detector binary, self-improvement, dock meters, the lock-screen/boot theme, talking to Pino (needs an account; build 15's signed note ships off until verified), Cypher's 3D city on Alpha (plan: docs/CYPHER-WORLD.md; the apartment shipped in build 16), his own 3D body (waits on his design and Zack's yes). See the design page for the plan.

## Tests

`python3 tests/cypher/test_cypherd.py`, `test_cypherd_phase2.py`, `test_cypherd_phase3.py`, `test_cypherd_phase4.py`, `test_cypher_one_mind.py`, `test_cypherd_phase5.py`, `test_cypherd_build12.py`, `test_cypherd_build12b.py`, `test_cypherd_build13.py`, `test_cypherd_build14.py`, `test_cypherd_build14b.py` and `test_cypherd_build15.py` (build 14 includes a headless GTK probe on a private broadwayd when available; all HTTP mocked) (run by `tests/test-rpi5-nova.sh`), and `bash tests/test-rpi5-touch-retry.sh`. The proxy, lease store, library, camfeed and a two-process failover test (`test_failover_e2e.py`) are versioned in `tools/cypher-alpha/` (installed on Alpha under `~/nova-projects/cypher/`).

### Build 15 fix: power_off dialog never raised (found on build 14, 15 Nov 10:16 PM ET)
Zack typed "Shut down"; the chat model replied "Shutting down. Confirm on the screen if you mean it." without
calling `power_off`, so no Confirm/Cancel dialog appeared (journal kind `turn`, no `pending` AUDIT line). The
unbacked-claim guard only knew search/look-up verbs, so it let the false claim through. Now (novad.py):
- a plain whole-message shutdown request ("shut down", "power off", "turn yourself off", ...) raises the
  physical dialog directly, without asking the model; only the on-screen Confirm click still runs it;
- a reply that mentions a confirm dialog/button or says it is shutting down, restarting or locking, in a turn
  where no tool returned pending, gets one nudge; if it still claims it, it is replaced with
  "No confirm dialog is up; nothing was started."
