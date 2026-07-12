# AI-OS (oais)

Prompt/voice-driven "AI orchestration layer" on top of a SteamOS-style,
installable, bootc-based custom Linux distro. Users describe what they want;
the OS reuses an existing app, or develops, tests, and registers a new one,
then hands back only the result.

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md). Design decisions and why
this repo looks the way it does: [`docs/DECISIONS.md`](docs/DECISIONS.md).
Steps that need a real machine (not this dev/CI environment):
[`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

**Status (updated 2026-07-12): Phase 0/1 done and verified, Phase 2 is a
tested prototype but not complete (2.7/2.8 missing), Phase 4's GUI boot
shell is being built ahead of Phase 2 completion at the user's request.**
Confirmed 2026-07-09: clean-installed the `oais-arm64` image on Apple
Silicon (UTM), rebooted, logged in, `bootc status` shows the right image.
The OS image itself is still just a minimal customized bootc image (no AI
layer baked in yet -- that's Phase 5). A standalone orchestrator prototype
for the closed-loop pipeline lives in [`orchestrator/`](orchestrator/) and
is developed/tested independently of the image build; it also now ships a
kiosk GUI boot shell (Firefox in `--kiosk` mode over a local `sway`
compositor, `orchestrator/webshell/`) with a live CLI log panel and
automatic window cleanup after login flows. That shell has gone through
several real-VM debug rounds (black screen, hung LLM connect, npm
timeouts/permissions, a broken image build, invisible login output, a
wrong CLI subcommand, a stuck OAuth window -- see `docs/DECISIONS.md`'s
2026-07-11 entries) but the fully-combined fixed state has not yet been
verified in one continuous boot-to-prompt run. See `docs/ROADMAP.md`'s
progress note and Appendix B for the full picture.

This repo is built on the [`ublue-os/image-template`](https://github.com/ublue-os/image-template)
pattern for [bootc](https://github.com/bootc-dev/bootc) images -- see that
project's README for the general mechanics of Containerfile/build.sh/Justfile.
This document only covers what's specific to AI-OS.

## Base image

`quay.io/fedora/fedora-bootc:latest` -- upstream Fedora's minimal bootc
base, no desktop environment, published multi-arch (x86_64 + aarch64).
See `docs/DECISIONS.md` for why (and why it's not `ghcr.io/ublue-os/base-main`
anymore -- that one's amd64-only).

Built for both architectures: `build.yml` pushes `ghcr.io/head77x/oais`
(amd64) and `ghcr.io/head77x/oais-arm64` (arm64) as separate images, not
one multi-arch manifest -- see `docs/DECISIONS.md`.

## Repository contents

- `Containerfile` -- image build entrypoint; sets the base image.
- `build_files/build.sh` -- package installs and OS branding, run inside the build.
- `system_files/` -- files copied verbatim into the image root (`etc/`, `usr/`).
- `disk_config/` -- `bootc-image-builder` configs for qcow2/ISO output.
- `oais.env` -- image name/registry/description variables consumed by the `Justfile`.
- `.github/workflows/build.yml` -- builds the OCI image and pushes to GHCR.
- `.github/workflows/build-disk.yml` -- builds qcow2/ISO disk images from the OCI image.
- `orchestrator/` -- Phase 2 closed-loop pipeline prototype (Task Spec, app registry, state machine) plus the Phase 4 kiosk GUI boot shell (`webshell/`). Copied into the image at `/usr/lib/oais/orchestrator` and launched by `system_files/etc/sway/config` on `aios` autologin -- see `orchestrator/README.md`.

## Building locally

Requires Podman, `bootc`, and `just` -- see `docs/LOCAL_SETUP.md` for install
steps and why this can't be exercised in the current dev sandbox.

```bash
just build          # build the OCI image locally
sudo just build      # build directly into root's container storage
sudo bootc switch --transport containers-storage localhost/oais:latest
```

## CI

`build.yml` runs on every push to `main` and publishes
`ghcr.io/head77x/oais:latest` (amd64) and `ghcr.io/head77x/oais-arm64:latest`
(arm64) once secrets are configured (see `docs/LOCAL_SETUP.md` for the
cosign signing key requirement before this will succeed).

`build-disk.yml` (qcow2/ISO disk images) now runs automatically after
`build.yml` succeeds on `main`, via a `workflow_run` trigger -- no manual
step needed anymore. It can still be triggered manually
(`workflow_dispatch`) to pick a single platform. If
`AWS_ACCESS_KEY_ID`/`AWS_S3_BUCKET` secrets are set, finished disk images
upload straight to S3; otherwise they're attached as workflow artifacts.
See `docs/LOCAL_SETUP.md` for the full secrets list.
