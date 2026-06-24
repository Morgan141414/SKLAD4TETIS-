#!/usr/bin/env bash
set -euo pipefail

cd /home/tassay/sklad

export PATH="$HOME/.local/bin:$PATH"
export SKLAD_DEV_AUTH_ENABLED="${SKLAD_DEV_AUTH_ENABLED:-true}"
export SKLAD_DEPLOYMENT_MODE="${SKLAD_DEPLOYMENT_MODE:-demo}"
export SKLAD_DATABASE_BACKEND="${SKLAD_DATABASE_BACKEND:-sqlite}"
export SKLAD_DATABASE_URL="${SKLAD_DATABASE_URL:-sqlite:///./sklad.db}"

exec uvicorn app.main:app --host 127.0.0.1 --port 8120
