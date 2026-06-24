#!/bin/bash
# Monthly ABC/XYZ analysis snapshot (all warehouses)
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

curl -sf -X POST "$API/analytics/abc-xyz/runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{}" > /dev/null && echo "[sklad_cron] abc-xyz monthly OK"

curl -sf -X POST "$API/notifications/generate-controlled-inventory" \
  -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[sklad_cron] pku-inventory-reminder OK"
