#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd -P)
arc="$root/var/integrations/arc"
pin=9fb4791cd3f5f0dd78b7fc75d9e572395daed171
export TMPDIR="$root/_scratch/tmp" UV_CACHE_DIR="$root/_scratch/cache/uv"
export XDG_CACHE_HOME="$root/_scratch/cache" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$UV_CACHE_DIR" "$root/var/integrations"
if [[ ! -d "$arc/.git" ]]; then
    git clone --single-branch --branch radar-selected-idea https://github.com/BUAAZhangHaonan/adversarial-research-copilot.git "$arc"
    git -C "$arc" switch --detach "$pin"
fi
if ! git -C "$arc" merge-base --is-ancestor "$pin" HEAD; then
    echo '现有 ARC 检出没有包含所需接口，请先核对该检出的版本。' >&2
    exit 1
fi
if [[ ! -x "$arc/.venv/bin/arc" ]]; then
    (cd "$arc" && uv sync --frozen)
fi
"$arc/.venv/bin/arc" handoff --help >/dev/null
git -C "$arc" log -1 --format='ARC %h %s'
