# Night City (Cypher's world; plan, simulated in build 12)

Zack's direction (Nov 15 2026): the city is called Night City (a private personal project; no CDPR assets). The 3D world runs on Alpha; the Pi deck is Cypher's
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
- **The deck is home.** The apartment renders on the deck itself; the city lives on Alpha. If Alpha is down,
  he is simply home.

## Engine
**three.js (WebGL2, WebGPU later)**, recommended: proven for exactly this by Pino; runs anywhere a browser
runs (Alpha, phone, deck); node is already on Alpha; scenes are driven from JSON state; stylized neon,
fog, rain and dithering are shader-level work; no editor install. **Godot 4** is the alternative if Zack
wants to build the city in an editor (better tooling, navmesh, animation, native perf; web export works but
is heavier). Either way: low-poly blockout, instanced buildings, emissive neon signs and bloom, height fog,
GPU rain particles, wet-street reflections faked with cubemaps/SSR-lite. A 1080p target fits easily on the iGPU.

## Start small: the apartment first
**Apartment (unit 9C, the deck).** Rendered on the deck itself as a small low-poly room (one scene, a few
hundred triangles, 30 fps at 1280x720 on the Pi 5; no Alpha needed): bed/charging nook, desk terminal,
shelf, a big rain-streaked window with neon light spilling in. Mood and drives place him: drained or
quiet hours = bed/nook, curiosity = terminal (look-ups, searches, X), check_grid = window, journal = desk;
mood sets the room light and the rain on the glass. The HUD panels stay around it.

**First city slice (on Alpha): one block outside his window.** The street below his building: a noodle
stall (social), a mag-line platform screen showing Pino's live feed (visit_pino), and the rooftop antenna
(check_grid). Fog, rain, neon, a few NPC silhouettes. The deck's window shows this street (iGPU stream)
when Alpha is up; when Cypher goes "out" he appears there and the deck shows an empty room with "OUT".

**Adding areas later.** Each new area is one self-contained module: a scene file plus a manifest entry
(name, places, moves it offers, which drives draw him there, how it connects to existing areas). The world
service loads whatever modules are installed; cypherd only ever sees the manifest, so no deck rebuild is
needed for a new area. New areas get added when Zack approves one (ideas: market, archive, arcade,
Rivet's garage); Cypher can propose an area through his nightly sleep like a tuning proposal, never build
or unlock it himself.

## Build 12 (simulated)
Places are a state field (apartment, noodle_stall); `go_to` and `eat` (+0.20 energy, 3 a day, 3 h apart) exist; cypherd writes `~/.local/state/cypher/world.json` (the manifest) every model call. The Alpha world service will later replace the simulated manifest.

## Phases (sessions = one focused build sitting)
1. A1 apartment on the deck + `go_to` inside it (bed, desk, terminal, window), tests: 2-3 sessions, one deck build.
2. C1 world service + first street slice on Alpha + window stream to the deck: 3-4 sessions.
3. C2+ one new area per approval: about 1-2 sessions each.

## Risks
VRAM and gaming contention (mitigated by iGPU rendering and pausing); headless Chromium RAM (systemd memory
cap, required by Zack's soak-test rule); scope creep; IP (original names and assets only); prompt injection
from X/web/Pino text shown in the world (display-only, labelled, never instructions); deck RAM if it ever
renders locally (prefer the stream); the world must never become a control path (no house, battery or tank).

## Zack decides
City name; the first street slice; which area comes next; where it renders (iGPU stream vs viewers only); whether it shows on Alpha's
ultrawide; LAN/tailnet only (recommended) or public; OK to install headless Chromium + three.js on Alpha;
the Pino screen. Decided: Cypher may go out during quiet hours (messages still never go out then); Cypher designs his own body (proposal, Zack approves).
