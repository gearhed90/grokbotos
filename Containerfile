# Allow build scripts to be referenced without being copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY orchestrator /orchestrator

# Base Image
# quay.io/fedora/fedora-bootc: minimal Fedora Atomic (bootc) image with no
# desktop environment, published multi-arch (x86_64 + aarch64). Switched
# from ghcr.io/ublue-os/base-main (2026-07-09): base-main is amd64-only,
# which blocks building/testing this image on arm64 (e.g. Apple Silicon
# Macs via UTM). See docs/DECISIONS.md for the full history.
# Not pinned to a digest yet -- quay.io isn't reachable from this dev
# sandbox to resolve one; pin it once resolvable (from CI logs or a
# machine with normal network access).
FROM quay.io/fedora/fedora-bootc:latest

### MODIFICATIONS
## make modifications desired in your image and install packages by modifying the build.sh script
## the following RUN directive does all the things required to run "build.sh" as recommended.

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    /ctx/build.sh

### LINTING
## Verify final image and contents are correct.
RUN bootc container lint
