#!/bin/bash
# Shared helpers for Grok Bot OS user-facing scripts.
# Sourced, not executed.

# grokbot_under_dir PATH ROOT
# True when PATH (after resolving ".." and existing symlinks) is ROOT
# itself or a path underneath ROOT.
grokbot_under_dir() {
    local path="$1"
    local root="$2"
    local real_path real_root
    real_root=$(realpath -m -- "$root")
    real_path=$(realpath -m -- "$path")
    [[ "$real_path" == "$real_root" || "$real_path" == "$real_root"/* ]]
}
