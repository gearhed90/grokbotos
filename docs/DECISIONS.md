# Decisions Log

Tracks the Phase 0/1 decisions called for in `ROADMAP.md`, and why. Append
new decisions here as later phases make them (LLM provider, STT engine,
vector index, sandbox tech, etc.) rather than losing them in commit messages.

## Base distro: Fedora Atomic (Universal Blue)

`ROADMAP.md` Phase 0 recommends this over an experimental Arch bootc setup
because Universal Blue has the most mature bootc tooling, docs, and
community. No reason to deviate for an MVP.

## Base image: `quay.io/fedora/fedora-bootc` (was `ghcr.io/ublue-os/base-main`, reversed 2026-07-09)

**Superseded, see below for the current choice.** Original reasoning
(still valid for why not Bazzite/Aurora/Bluefin): `ublue-os/image-template`'s
default `Containerfile` points at `ghcr.io/ublue-os/bazzite:stable`, a full
gaming-oriented desktop image. That's the wrong foundation here: Phase 4 of
the roadmap throws away the desktop entirely and replaces it with a
dedicated fullscreen prompt/voice shell (no icons, no taskbar). Starting
from a full GNOME/KDE desktop today just means stripping it back out later.
`base-main` was chosen as Universal Blue's minimal image with no desktop
environment, meant as a starting point for exactly this kind of build.

**Why it was reversed**: `ghcr.io/ublue-os/base-main` only publishes an
amd64 build (confirmed directly -- `docker manifest inspect` returns a
single-architecture manifest, not a multi-arch index). That silently
blocks building or testing this image on arm64 at all, which only surfaced
once the user (on an Apple Silicon Mac) actually tried to build an arm64
disk image and `bootc-image-builder` failed on the architecture mismatch.
This should have been checked before recommending an arm64 test path in
the first place, not discovered several failed CI runs in.

Switched to `quay.io/fedora/fedora-bootc:latest` -- plain upstream Fedora's
bootc image, published multi-arch (x86_64 + aarch64, per Fedora bootc/CoreOS
infrastructure and corroborated via web search; **not independently
verified by digest inspection**, since this dev sandbox's network policy
blocks `quay.io` outbound -- see `curl -sS "$HTTPS_PROXY/__agentproxy/status"`).
Not pinned to a digest yet for the same reason; pin it once resolvable from
an unrestricted network (CI logs, or the user's own machine). Cost of this
switch: lose Universal Blue's own tooling/update scripts baked into
`base-main` -- acceptable since the current Containerfile doesn't use any
of it (`dnf5 install` + a `systemctl enable`), and Phase 4 replaces the
desktop/update UX anyway.

## Template source: inlined, not forked separately

`ROADMAP.md` Phase 0 says to fork `ublue-os/image-template` to get the base
template. Since the working repo (`head77x/oais`) already existed as the
designated target, the template's files were copied directly into it
instead of maintaining a second forked repository — same result (a working
Containerfile/Justfile/CI baseline), one fewer repo to keep in sync.

## `/etc/os-release` branding approach

`base.sh` `sed`s `NAME`/`PRETTY_NAME` in `/usr/lib/os-release` (which
`/etc/os-release` symlinks to) but leaves `ID`/`ID_LIKE` as `fedora`. This
matches how Bazzite/Aurora/Bluefin brand themselves — package managers,
`bootc`, and other tooling key off `ID`, so changing it breaks things for no
benefit at this stage. `VARIANT`/`VARIANT_ID`/`HOME_URL` are added instead.

## LLM connection model (2026-07-08, ROADMAP.md 2.2): hybrid, auth-based cloud + auto-installed local

Neither pure cloud API keys nor pure local-only was chosen. Both modes are
supported, but the UX for each is deliberately not the obvious default:

- **Cloud providers**: no raw API key entry. The user connects an account
  via a login/auth flow (like `claude login`/`gh auth login`), not by
  pasting a key into a config file. `orchestrator/orchestrator/providers/cloud_oauth.py`
  implements the generic OAuth 2.0 Device Authorization Grant (RFC 8628)
  state machine this requires -- request a device code, show the user a
  `verification_uri`/`user_code`, poll the token endpoint until authorized.
  It is provider-agnostic on purpose: **no specific provider (Anthropic,
  OpenAI, Google, ...) is wired up yet**, because each one's actual
  device-flow endpoint URLs, client ID, and scopes need to be confirmed
  from that provider's real documentation before being hardcoded. Guessing
  those values would produce code that looks like it works but silently
  fails against the real service, which is worse than leaving it
  unimplemented. Concrete provider subclasses (`AnthropicAuthProvider`,
  etc.) are follow-up work, one at a time, each backed by that provider's
  actual published OAuth docs.
- **Local models**: if the user picks local, the OS should fetch and
  install the model itself, not send the user to a terminal.
  `orchestrator/orchestrator/providers/local_ollama.py` wraps the
  [Ollama](https://ollama.com) CLI (`ollama pull`/`ollama list`) for this
  -- Ollama was picked over raw llama.cpp/vLLM because it already has a
  one-command model pull/run story that matches "auto-installed" directly,
  and ROADMAP.md 2.2 already names it as a candidate. This is real
  subprocess-calling code, not a stub, but it can't be exercised in this
  dev sandbox (no `ollama` binary here -- see the section below) and needs
  verification on a real machine.

Which specific cloud providers to support, and the actual routing rule for
"하이브리드" (when to use cloud vs. local) are still open — this decision
only fixes the *shape* of both connection paths, not provider selection or
routing policy.

## Concrete cloud providers (2026-07-08, revised same day): wrap the official CLIs as subprocesses, don't touch their credentials

Anthropic and xAI both get the "install it, log in with your own account,
it just works" treatment the user asked for -- via the same mechanism for
both, `providers/cli_subprocess.py`: install the vendor's own official CLI,
let the user run its own login command, and call it as a subprocess
(`<cli> -p "<prompt>"`) for every completion. Neither provider reads a
credential file or calls a vendor REST API directly. The CLI handles 100%
of its own auth, invisibly to us, exactly as it would from a human's
terminal.

This replaces an earlier same-day version of this decision that had two
*different* mechanisms per vendor (Anthropic via a raw `x-api-key` REST
call, xAI via directly reading `~/.grok/auth.json` and calling
`api.x.ai` ourselves with the extracted token). That design was wrong for
what was actually being asked, not just suboptimal: reading and reusing a
CLI's own stored OAuth credential in a separate unofficial HTTP client is
the "spoof a client's identity" pattern Anthropic's Jan-Apr 2026
enforcement specifically targets (see below) -- running the official
binary itself is not that at all, and there was never a good reason to
treat xAI differently once that was clear.

- **`providers/claude_cli.py` (`ClaudeCliProvider`)**: wraps `claude -p`.
  Installed via `npm install -g @anthropic-ai/claude-code` if missing.
  This is unambiguously fine -- it's the same Claude Code binary and the
  same login (`claude login`) a user would use directly, just invoked by
  our orchestrator instead of typed by hand. The thing that *would* violate
  Anthropic's Consumer Terms of Service, and is enforced server-side since
  January 2026 (escalated April 2026, with account bans): extracting
  Claude Code's stored OAuth token and presenting it directly to
  `api.anthropic.com` from a separate, unofficial HTTP client -- which is
  what the previous version of this decision (and `AnthropicApiKeyProvider`
  used generically, not for that purpose) did not do, but is worth naming
  explicitly since it's the actual line. Sources: [Anthropic clarifies ban
  on third-party tool access to Claude (The
  Register)](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/),
  [Anthropic Ends Paid Access for Claude in Third-Party Tools Like OpenClaw
  (MLQ News)](https://mlq.ai/news/anthropic-ends-paid-access-for-claude-in-third-party-tools-like-openclaw/).
  `providers/anthropic_api_key.py` (official `x-api-key` REST auth, via
  the `SecretStore` interface) is kept as a fallback for setups without
  Claude Code installed -- this remains explicitly fine per Anthropic's own
  guidance, it's just no longer the primary path.

- **`providers/xai_grok.py` (`GrokCliProvider`)**: wraps
  `grok --no-auto-update -p`. Installed via
  `npm install -g @xai-official/grok` if missing. `--no-auto-update` is
  confirmed from the CLI's own documented smoke-test example
  (`grok --no-auto-update -p "Say ok."`). This also sidesteps the
  `~/.grok/auth.json` schema uncertainty the previous version of this
  provider had to work around -- we no longer read that file at all.

Both share `providers/cli_subprocess.py`'s `CliSubprocessProvider`:
`ensure_ready()` installs the CLI if absent, then runs a cheap real prompt
as a login-state smoke test (there's no reliably-named side-effect-free
"am I logged in" subcommand confirmed for either CLI) and caches success;
`complete_json()` embeds the JSON-schema instruction in the prompt text
(same pattern as the Ollama/xAI-REST/Anthropic-REST providers) and parses
stdout.

## Environment/CI limitations of this dev sandbox

This repo was scaffolded from a cloud dev container with no `/dev/kvm`, no
`podman`/`bootc`/`just`/`qemu` installed, and no privileged container
support (loop devices for `bootc-image-builder` need real root + KVM). That
means every "boot it and check" item in Phase 0/1 (`bootc status`, ISO
install test, `bootc switch` test) had to be left unchecked here and pushed
to `docs/LOCAL_SETUP.md` for the user's own machine. GitHub Actions
(`build.yml`/`build-disk.yml`) run on real `ubuntu-24.04` runners and don't
have this limitation — those are expected to work once secrets are set up.

## `build-disk.yml` fix: explicit `podman pull` before bootc-image-builder (2026-07-08)

First real run of `build-disk.yml` failed with `ghcr.io/head77x/oais:latest:
image not known` -- newer `bootc-image-builder` versions stopped pulling
the target image themselves and expect it already present in the same
podman storage the build step mounts. Added a `docker/login-action` step
(the package is private, tied to this private repo) plus an explicit
`sudo podman pull ...` step before the build step, matching the error
message's own suggested fix. Only found by actually running the workflow
-- this wasn't something to catch by reading the template beforehand.

Two more issues surfaced on subsequent runs, same pattern (only found by
actually executing the workflow):

- `docker/login-action` logs in the runner user's own credential store,
  but the pull (and bootc-image-builder itself) run as root via `sudo`,
  which keeps a separate one -- login reported success but the pull still
  got `unauthorized`. Fixed by logging in with `sudo podman login`
  instead, so both steps share root's credential store.
- `ghcr.io/ublue-os/base-main` doesn't declare a default root filesystem
  type in its container metadata, so bootc-image-builder failed with
  `missing required info: DefaultRootFs`. This is a known issue with
  Universal Blue-derived images (confirmed via their own Discourse forum,
  not guessed) -- fixed by passing `--rootfs ext4` explicitly via
  `additional-args`. (Left in place after switching to fedora-bootc too --
  explicit is still fine even if no longer strictly required.)

## arm64 image build + two more bugs found testing it (2026-07-09)

Following the base image switch above, `build.yml` now builds both
architectures natively via a `platform: [amd64, arm64]` matrix
(`ubuntu-24.04` / `ubuntu-24.04-arm` runners). amd64 and arm64 are pushed
as **separately-named images** (`oais` / `oais-arm64`), not merged into one
multi-arch manifest list -- simpler to reason about and debug than wiring
up cross-job digest aggregation for a manifest-list push, at the cost of
the registry not "just resolving the right arch" from a single tag.
Revisit if that's worth it later. `build-disk.yml` picks the matching
image name based on its `platform` input.

Two bugs found while wiring this up, both in `disk_config/iso.toml`:

- The kickstart's `bootc switch` target was hardcoded to
  `ghcr.io/head77x/oais:latest` -- on an arm64 build this would have
  switched an arm64-installed system to an amd64 image. `build-disk.yml`
  now `sed`s the correct image name in before the build step.
- `org.fedoraproject.Anaconda.Modules.Users` was in the installer's
  disabled-modules list (inherited from the `ublue-os/image-template`
  example this was based on, uncaught until now). With it disabled and no
  `user`/`rootpw` in the kickstart, an install would finish with **no way
  to log in** -- silently failing Phase 1's actual acceptance criterion.
  Removed from the disable list so Anaconda's normal interactive
  account-creation screen runs.

## Phase 4 boot shell + LLM connection onboarding (2026-07-09)

Reordered ahead of 2.7/2.8 at the user's direction: the closed-loop
pipeline is moot if there's no working way to actually connect an LLM
provider on a real installed system, so that gate needed to be solid
first, wired into the actual boot flow -- not just exercised as library
calls from a dev machine like everything in `orchestrator/` so far.

**`orchestrator/orchestrator/onboarding.py` + `onboarding_cli.py`**: the
provider-agnostic connection logic (pick a provider, drive its
install/login, remember the choice in `~/.config/oais/provider.json`) is
separated from the console UI on top of it, same DI-for-testability
pattern as the rest of `orchestrator/`. `onboarding_cli.py` is a real,
runnable, text-based flow verified in this dev sandbox (piped stdin) --
it's the console-only OS's actual Phase 2.1 입력 레이어 for now, not a
placeholder. Wrapping it in graphical chrome is a presentation-layer
concern the logic underneath doesn't care about.

**Claude vs. Grok connection shape, revised same day**: originally
(see the Anthropic/xAI research further up this doc) Claude was going to
use a pasted `claude setup-token` since this OS had no browser and
`claude login` needs a local one. The user then decided the OS should
just ship a browser by default rather than route around not having one --
`docs/DECISIONS.md`'s job is to keep this kind of reversal visible, not
just the latest state. `connect_claude_via_browser()` is now the primary
path, same shape as `connect_grok()` (try silently, then run the login
command with real stdio so the CLI's own browser-opening behavior takes
over); `connect_claude_with_token()` stays as a fallback for before a
graphical session exists yet.

**Browser + minimal Wayland session baked into the image**: `firefox` +
`sway` (compositor) + `foot` (terminal) installed via `build_files/build.sh`,
matching Phase 4's "전용 컴포지터 기반 풀스크린 셸" -- one thing running
fullscreen (a terminal running `onboarding_cli.py`), no panel, no window
chrome; Firefox gets fullscreen too when the shell spawns it for login,
and focus returns to the shell when it closes. A dedicated `aios` system
account runs this, independent of whatever admin username Anaconda's
interactive kickstart creates at install time (nothing in the image can
know that name in advance).

**Caught before committing, not after another failed CI-style round
trip**: `/opt` and `/home` are symlinked to `/var/opt`/`/var/home` on
this ostree/bootc base, and `/var` content written during the image
build isn't guaranteed to survive into the shipped image (the
Containerfile template this project started from even has a comment
about exactly this for `/opt`). The original draft of this change put
the app under `/opt/oais` and the kiosk config under
`~aios/.config/sway/` and `~aios/.bash_profile` -- all of which could
have silently vanished on first boot. Moved to `/usr/lib/oais/orchestrator`
(app code), `/etc/sway/config` (system-wide sway config instead of
per-user), and a login-shell script at `/usr/local/bin/oais-shell-launch`
(instead of `.bash_profile`) -- `/usr` and `/etc` are the parts of an
ostree/bootc image actually guaranteed to persist.

**Still genuinely unverified**: this dev sandbox has no display to boot
a graphical session against at all. Autologin-into-sway pattern, the
sway config, SELinux policy (Fedora bootc ships enforcing by default,
and none of this was written with a specific SELinux module in mind) --
all written from documented patterns, none boot-tested. Expect at least
one round of fixes once actually tried in the VM, same as
`build.yml`/`build-disk.yml` needed.

## Phase 4 boot shell: text TUI replaced with a real GUI web shell (2026-07-10)

The first boot-tested build (arm64 disk image, `main`@`a266e5f`) actually
worked -- tty1 autologin -> sway -> the onboarding shell ran and showed
its provider-selection screen. Two problems surfaced from that first real
test, both from actual screenshots the user provided:

**1. Korean text rendered as tofu boxes.** The image had no CJK-capable
font installed, so `foot` fell back to boxes for any Hangul the shell
printed. Fixed by adding `google-noto-sans-cjk-ttc-fonts` to `build.sh`'s
`dnf5 install` line.

**2. Wrong UI shape entirely.** The shell that actually appeared was a
numbered text menu (`[1] Claude (Anthropic)` etc.) in a terminal. The
user's explicit expectation, stated after seeing the screenshot: once
AI-OS is installed, the *first* screen must be a desktop-style GUI --a
prompt input at the center, and a dock/taskbar-like row of icons at the
bottom for both installed programs and LLM-connection options. The
prompt input must be visibly disabled until an LLM icon is clicked and a
connection succeeds. A text menu in a terminal does not meet that bar,
regardless of how correct the underlying connection logic is.

**Decision: build this as a local HTTP server + static HTML/CSS/JS page,
displayed via the already-baked-in Firefox in `--kiosk` mode** --
rather than a native toolkit (GTK4, Qt). Reasoning:

- Firefox is already a hard requirement in the image (OAuth login for
  `claude`/`grok` needs a real browser -- see the entry above this one).
  Reusing it for the shell UI itself means no new heavyweight package
  (GTK4 + PyGObject + introspection data, or Qt + PySide) has to be
  added just to draw a box and some icons.
  `sway`'s existing `for_window [app_id="firefox"] fullscreen enable`
  rule already fullscreens whatever Firefox window is on screen, so the
  OAuth login flow (which also opens a Firefox window) and the shell
  itself share one visual language for free.
- The orchestrator package is already pure-stdlib Python (see its
  README's "stdlib only, on purpose" note); `http.server` keeps that
  true for the server side too, no new dependency to vendor or
  `dnf install`.
- HTML/CSS text rendering doesn't have the CJK tofu-box problem GTK/Qt
  can also hit if the wrong font stack is picked -- browsers fall back to
  system fonts (now including the Noto CJK package above) correctly by
  default.

**Shape of the result** (`orchestrator/webshell/`):
`server.py` (stdlib `http.server`, binds `127.0.0.1` only) serves
`static/index.html`+`style.css`+`app.js` and a small JSON API
(`/api/status`, `/api/apps`, `/api/choices`, `/api/connect`,
`/api/connect-token`, `/api/prompt`). `connect.py` runs the actual
connection flow (which blocks on a real subprocess during browser OAuth)
on a background thread, using a lock-protected `ConnectionState`
(`state.py`) so `/api/status` keeps answering polls while that's in
flight -- the frontend polls every 1.5s and enables the prompt input the
moment `connected` flips true. None of `onboarding.py`'s connection
logic changed; this only replaces the UI layer that was driving it.
`webshell_cli.py` is what `system_files/etc/sway/config` now execs
(replacing the old `foot -e ... onboarding_cli` line); `onboarding_cli.py`
itself is kept as-is for headless use (SSH, recovery console) since the
underlying logic is identical either way.

**Still genuinely unverified**: same caveat as before -- no display in
this dev sandbox. Logic-level tests only (`tests/test_webshell.py`,
including a real-socket integration test against routes that don't touch
subprocesses). The actual "click Claude icon -> Firefox OAuth window
opens on top -> closing it reveals the shell again with the prompt now
enabled" flow has never been observed end-to-end.
