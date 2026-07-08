# Allow build scripts to be referenced without being copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files

# Base Image
# ublue-os/base-main: minimal Fedora Atomic (bootc) image with no desktop
# environment baked in. Chosen over desktop-oriented images (Bazzite/Aurora/
# Bluefin) because Phase 4 of the roadmap replaces the desktop entirely with
# a dedicated fullscreen prompt/voice shell -- carrying GNOME/KDE this early
# would just be dead weight to strip out later.
# See docs/DECISIONS.md for the full rationale.
FROM ghcr.io/ublue-os/base-main:latest@sha256:3d8051d4ce422083a133ee84e36ed417aa11f996d2cf1e1d7df3eef47ce32d86

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
