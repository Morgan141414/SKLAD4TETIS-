#!/bin/bash
# Daily maintenance: low stock, expiry, quarantine notifications
set -euo pipefail

API="${SKLAD_API_URL:-http://127.0.0.1:8120/api/v1}"
: "${SKLAD_JWT_HMAC_SECRET:?Set SKLAD_JWT_HMAC_SECRET for cron token signing}"

TOKEN=$(python3 -c "
import os
import jwt, datetime
payload = {
  \"sub\": \"system\",
  \"iss\": os.getenv(\"SKLAD_JWT_ISSUER\") or \"tetis\",
  \"aud\": os.getenv(\"SKLAD_JWT_AUDIENCE\") or \"sklad\",
  \"roles\": [\"warehouse_manager\"],
  \"exp\": int((datetime.datetime.utcnow() + datetime.timedelta(hours=1)).timestamp()),
}
print(jwt.encode(payload, os.environ[\"SKLAD_JWT_HMAC_SECRET\"], algorithm=\"HS256\"))
" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "[sklad_cron] Failed to generate token" >&2
  exit 1
fi

curl -sf -X POST "$API/notifications/generate-low-stock" \
  -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[sklad_cron] low-stock OK"

curl -sf -X POST "$API/notifications/generate-expiry?days=30" \
  -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[sklad_cron] expiry OK"

curl -sf -X POST "$API/notifications/generate-quarantine?days=3" \
  -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[sklad_cron] quarantine OK"
