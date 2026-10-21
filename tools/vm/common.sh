#!/bin/bash
# Shared settings for the VM test tools. Override with environment variables.
# GBVM_DIR: work dir for disks, firmware vars, sockets, logs (default: <repo>/.vm)
GBVM_DIR=${GBVM_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.vm}
GBVM_IMAGE=${GBVM_IMAGE:-localhost/oais:latest}
GBVM_MEM=${GBVM_MEM:-4096}
GBVM_SMP=${GBVM_SMP:-4}
GBVM_OVMF=${GBVM_OVMF:-/usr/share/OVMF}
export GBVM_DIR GBVM_IMAGE
mkdir -p "$GBVM_DIR/shots"
