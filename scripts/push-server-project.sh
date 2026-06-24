#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 2 ]]; then
  printf 'Usage: %s <local-name> <remote-path>\n' "$0" >&2
  printf 'Example: %s mis /home/admin2/mis\n' "$0" >&2
  exit 2
fi

REMOTE_HOST="${REMOTE_HOST:-admin2@100.76.173.85}"
LOCAL_NAME="$1"
REMOTE_PATH="${2%/}"
LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_PATH="$LOCAL_ROOT/server-projects/$LOCAL_NAME"

if [[ ! -d "$LOCAL_PATH" ]]; then
  printf 'Local project not found: %s\n' "$LOCAL_PATH" >&2
  exit 1
fi

rsync -az --info=progress2 \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  "$LOCAL_PATH/" "$REMOTE_HOST:$REMOTE_PATH/"

printf 'Pushed %s -> %s:%s\n' "$LOCAL_PATH" "$REMOTE_HOST" "$REMOTE_PATH"
