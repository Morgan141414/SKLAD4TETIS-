#!/bin/bash
# Daily maintenance: low stock, expiry, quarantine notifications
API="http://127.0.0.1:8120/api/v1"
TOKEN=$(python3 -c "
import jwt, datetime
payload = {
  \"sub\": \"system\",
  \"iss\": \"tetis\",
  \"aud\": \"sklad\",
  \"roles\": [\"warehouse_manager\"],
  \"exp\": int((datetime.datetime.utcnow() + datetime.timedelta(hours=1)).timestamp()),
}
print(jwt.encode(payload, \"finalboss2-staging-secret-key-change-before-prod\", algorithm=\"HS256\"))
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
