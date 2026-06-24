#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s <remote-path> [local-name]\n' "$0" >&2
  printf 'Example: %s /home/admin2/mis mis\n' "$0" >&2
  exit 2
fi

REMOTE_HOST="${REMOTE_HOST:-admin2@100.76.173.85}"
REMOTE_PATH="${1%/}"
LOCAL_NAME="${2:-$(basename "$REMOTE_PATH")}"
LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_PATH="$LOCAL_ROOT/server-projects/$LOCAL_NAME"

mkdir -p "$LOCAL_PATH"

rsync -az --info=progress2 \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  "$REMOTE_HOST:$REMOTE_PATH/" "$LOCAL_PATH/"

printf 'Pulled %s:%s -> %s\n' "$REMOTE_HOST" "$REMOTE_PATH" "$LOCAL_PATH"
