# Decisions Log

Tracks the Phase 0/1 decisions called for in `ROADMAP.md`, and why. Append
new decisions here as later phases make them (LLM provider, STT engine,
vector index, sandbox tech, etc.) rather than losing them in commit messages.

## Base distro: Fedora Atomic (Universal Blue)

`ROADMAP.md` Phase 0 recommends this over an experimental Arch bootc setup
because Universal Blue has the most mature bootc tooling, docs, and
community. No reason to deviate for an MVP.

## Base image: `ghcr.io/ublue-os/base-main` (not Bazzite/Aurora/Bluefin)

`ublue-os/image-template`'s default `Containerfile` points at
`ghcr.io/ublue-os/bazzite:stable`, a full gaming-oriented desktop image.
That's the wrong foundation here: Phase 4 of the roadmap throws away the
desktop entirely and replaces it with a dedicated fullscreen
prompt/voice shell (no icons, no taskbar). Starting from a full GNOME/KDE
desktop today just means stripping it back out later.

`base-main` is Universal Blue's minimal image with no desktop environment,
meant as a starting point for exactly this kind of custom build. Pinned by
digest in `Containerfile` for reproducible builds
(`sha256:3d8051d4ce422083a133ee84e36ed417aa11f996d2cf1e1d7df3eef47ce32d86`
as of 2026-07-08 — Renovate/Dependabot will need a manual rule or periodic
re-pin since `base-main` isn't auto-tracked by the template's default bots).

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
  `additional-args`.
