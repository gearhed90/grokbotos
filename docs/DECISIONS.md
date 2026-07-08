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

## Environment/CI limitations of this dev sandbox

This repo was scaffolded from a cloud dev container with no `/dev/kvm`, no
`podman`/`bootc`/`just`/`qemu` installed, and no privileged container
support (loop devices for `bootc-image-builder` need real root + KVM). That
means every "boot it and check" item in Phase 0/1 (`bootc status`, ISO
install test, `bootc switch` test) had to be left unchecked here and pushed
to `docs/LOCAL_SETUP.md` for the user's own machine. GitHub Actions
(`build.yml`/`build-disk.yml`) run on real `ubuntu-24.04` runners and don't
have this limitation — those are expected to work once secrets are set up.
