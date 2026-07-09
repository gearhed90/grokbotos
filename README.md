# AI-OS (oais)

Prompt/voice-driven "AI orchestration layer" on top of a SteamOS-style,
installable, bootc-based custom Linux distro. Users describe what they want;
the OS reuses an existing app, or develops, tests, and registers a new one,
then hands back only the result.

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md). Design decisions and why
this repo looks the way it does: [`docs/DECISIONS.md`](docs/DECISIONS.md).
Steps that need a real machine (not this dev/CI environment):
[`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

**Status: Phase 0/1 done and verified, Phase 2 in progress.** Confirmed
2026-07-09: clean-installed the `oais-arm64` image on Apple Silicon (UTM),
rebooted, logged in, `bootc status` shows the right image. The OS image
itself is still just a minimal customized bootc image (no AI layer baked
in yet -- that's Phase 5). A standalone orchestrator prototype for the
closed-loop pipeline lives in [`orchestrator/`](orchestrator/) and is
developed/tested independently of the image build.

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
- `orchestrator/` -- Phase 2 closed-loop pipeline prototype (Task Spec, app registry, state machine). Standalone Python, not yet wired into the image -- see `orchestrator/README.md`.

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
