# Cypher's city (plan, nothing built yet)

Zack's direction (Nov 15 2026): a Night City-like world (neon, rain, dense), original and only inspired by
Cyberpunk 2077 (no CDPR names, assets, logos or fonts). The 3D world runs on Alpha; the Pi deck is Cypher's
apartment in that city. Inspired by Pino (pinos.world), not a copy.

## What Pino does (sources)
- An LLM picks 1-3 moves from the moves the world offers; needs and feelings are computed every second with
  no model; the world carries out or refuses moves; a written character sheet he partly rewrites in his sleep
  (https://pinos.world/facts).
- Town built with three.js on WebGPU; dithering computed at material level, not post-processing; brain
  originally on a Raspberry Pi (https://discourse.threejs.org/t/autonomous-ai-bird-living-in-a-small-town-on-the-internet/93707),
  moved to its own server on Oct 6 2026 (https://pinos.world/facts).
- "Decide, then speak", threads, eyes, and "a world in one file": a manifest of what's there, what can be
  done, how it feels, the time and who's around; "neighbours" (many minds in one world) is on the roadmap
  (https://pinos.world/what-ships-next).
- Public keyless API: /api/v1/now, /feed, /mind, /memories, /who (https://pinos.world/developers).

## Architecture
- **Mind stays on the deck.** cypherd remains the only mind (Alpha's standby when it holds the lease). The
  world never decides, approves or unlocks anything; it only offers places/moves and reports what happened.
- **World service on Alpha** (`cypher-world`, user service, MemoryMax cap): a small authoritative sim
  (Python stdlib or Node) holding Cypher's position, the time of day, weather and the place manifest, plus a
  static three.js client. It listens on Alpha's LAN + tailnet addresses with its own token file (same pattern
  as the brain proxy; no change to cypher-brain-proxy or cypherd-alpha needed).
- **Protocol** (Pino's manifest idea): `GET /world/manifest` (places, moves on offer, weather, time, who's
  around), `POST /world/move {"go_to": place}` (from cypherd only, validated), `GET /world/state` (where he is,
  what he sees). cypherd gets one new action, `go_to(place)`, offered only for places in the manifest, with caps.
- **Rendering:** the three.js client renders in whatever views it: a window or the wallpaper on Alpha's
  ultrawide, a phone over Tailscale. For the deck, a headless Chromium on Alpha's **Raphael iGPU** (the RX
  9060 XT's 16 GB VRAM is ~15 GB used by Qwen3-VL and games) renders a 1280x720 at 10-15 fps stream (MJPEG or
  WebRTC) only while someone watches. In gaming mode it pauses and the deck shows "city offline".
- **The deck is home.** When Cypher is home, the deck shows the current avatar in his apartment (HUD stays).
  When he is out, a "window" panel on the deck shows the city stream with "OUT: <district>". If Alpha is down,
  he is simply home.

## Engine
**three.js (WebGL2, WebGPU later)**, recommended: proven for exactly this by Pino; runs anywhere a browser
runs (Alpha, phone, deck); node is already on Alpha; scenes are driven from JSON state; stylized neon,
fog, rain and dithering are shader-level work; no editor install. **Godot 4** is the alternative if Zack
wants to build the city in an editor (better tooling, navmesh, animation, native perf; web export works but
is heavier). Either way: low-poly blockout, instanced buildings, emissive neon signs and bloom, height fog,
GPU rain particles, wet-street reflections faked with cubemaps/SSR-lite. A 1080p target fits easily on the iGPU.

## The city (original names, placeholders)
| Place | Feel | Drive / mood that sends him | What he does there |
|---|---|---|---|
| Apartment, unit 9C (the deck) | small, warm, rain on the window | drained, quiet hours, low energy | rest, sleep, journal |
| Lantern Row (night market, noodle stalls) | crowds, steam, chatter | social high / lonely | people-watch, NPC small talk (no real people) |
| The Archive Spire (data library) | cold blue, terminals | curiosity | look_up / web_search shown as reading terminals |
| Signal Roof (antenna farm, billboards) | wind, skyline | check_grid, x_lookup | watches the grid; X posts on giant billboards |
| Static Alley (arcade, glitch neon) | loud, flickering | boredom / restless | games, graffiti of his mood (like Pino's art) |
| Rivet's Garage (workshop) | sparks, tools | focus / locked-in | tinkering; later the tank and Rivet |
| Mag-line platform | trains passing | visit_pino | a station screen shows Pino's live feed ("Pino, from pinos.world") |

Mood -> world: drained = heavy rain, dim neon, heads home; content = light drizzle, warm signs; restless =
flicker, crowds; lonely = empty streets. Real Eastern time drives day/night; in quiet hours he is home asleep.

## Phases and effort (sessions = one focused build sitting)
1. W0 design + greybox of 3 places, camera, rain/fog/neon look on Alpha: 1-2 sessions.
2. W1 world service + manifest + all 7 places, Cypher's body (a floating node/drone, "a node, not a pet"), walking between places: 3-5.
3. W2 cypherd `go_to` + place-aware manifest + world perception, tests: 2 (one deck image build).
4. W3 deck window stream + HUD "OUT" state, iGPU headless renderer with memory cap: 2.
5. W4 polish: dithering shaders, NPC crowds, billboards, Pino screen, weather from mood: ongoing.

## Risks
VRAM and gaming contention (mitigated by iGPU rendering and pausing); headless Chromium RAM (systemd memory
cap, required by Zack's soak-test rule); scope creep; IP (original names and assets only); prompt injection
from X/web/Pino text shown in the world (display-only, labelled, never instructions); deck RAM if it ever
renders locally (prefer the stream); the world must never become a control path (no house, battery or tank).

## Zack decides
City name and districts; where it renders (iGPU stream vs viewers only); whether it shows on Alpha's
ultrawide; LAN/tailnet only (recommended) or public; OK to install headless Chromium + three.js on Alpha;
Cypher's body style; whether he may leave home during quiet hours (recommended no); the Pino screen.
