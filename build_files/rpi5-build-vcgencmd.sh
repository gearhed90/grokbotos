#!/bin/bash
# Builder stage only (Containerfile.rpi5, stage "vcgencmd"). Compiles just
# vcgencmd from raspberrypi/utils at a pinned commit. Fedora has no package
# for it. The compiler and git stay in this stage; the final image only gets
# /out/vcgencmd, which links nothing but glibc.
# vcgencmd asks the VideoCore firmware for throttling, undervoltage, clocks
# and temperatures (vcgencmd get_throttled) through /dev/vcio.
set -euo pipefail

# Bump on purpose, after reading the vcgencmd/ changes upstream.
RPI_UTILS_URL=https://github.com/raspberrypi/utils
RPI_UTILS_COMMIT=b8961eb9a689a3c0465db108176d0ee425379730 # 2026-10-26

# gcc-c++: upstream project() enables C++ by default, though vcgencmd is C.
dnf5 install -y --disablerepo=fedora-cisco-openh264 gcc gcc-c++ cmake make git-core

src=/tmp/rpi-utils
git init -q "$src"
git -C "$src" fetch -q --depth 1 "$RPI_UTILS_URL" "$RPI_UTILS_COMMIT"
git -C "$src" checkout -q FETCH_HEAD
[[ "$(git -C "$src" rev-parse HEAD)" == "$RPI_UTILS_COMMIT" ]] || {
    echo "raspberrypi/utils checkout is not ${RPI_UTILS_COMMIT}" >&2
    exit 1
}

cmake -S "$src/vcgencmd" -B /tmp/vcgencmd-build \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
cmake --build /tmp/vcgencmd-build
install -D -m 0755 /tmp/vcgencmd-build/vcgencmd /out/vcgencmd

# Only glibc at runtime, so nothing else has to be copied into the image.
needed=$(objdump -p /out/vcgencmd | awk '/NEEDED/ {print $2}' | sort | tr '\n' ' ')
[[ "$needed" == "libc.so.6 " ]] || {
    echo "vcgencmd links more than libc: ${needed}" >&2
    exit 1
}
