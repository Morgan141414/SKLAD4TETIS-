#!/usr/bin/env bash
set -euo pipefail

cd /home/tassay/sklad

PORT="${SKLAD_SENSOR_PORT:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}"
DEVICE_ID="${SKLAD_SENSOR_DEVICE_ID:-1}"
API="${SKLAD_API_URL:-http://127.0.0.1:8120}"
BAUD="${SKLAD_SENSOR_BAUD:-9600}"
PARITY="${SKLAD_SENSOR_PARITY:-N}"
PROTOCOL="${SKLAD_SENSOR_PROTOCOL:-lines}"

exec /home/tassay/sklad/scripts/sklad_serial_sensor_bridge.py \
  --port "$PORT" \
  --baud "$BAUD" \
  --parity "$PARITY" \
  --api "$API" \
  --device-id "$DEVICE_ID" \
  --protocol "$PROTOCOL"
