#!/bin/bash
# Monthly ABC/XYZ analysis snapshot (all warehouses)
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

curl -sf -X POST "$API/analytics/abc-xyz/runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{}" > /dev/null && echo "[sklad_cron] abc-xyz monthly OK"

curl -sf -X POST "$API/notifications/generate-controlled-inventory" \
  -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[sklad_cron] pku-inventory-reminder OK"
