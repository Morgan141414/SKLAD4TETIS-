#!/usr/bin/env bash
set -euo pipefail

cd /home/tassay/sklad

PORT="${SKLAD_SENSOR_PORT:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}"
DEVICE_ID="${SKLAD_SENSOR_DEVICE_ID:-1}"

echo "== device =="
ls -l "$PORT" /dev/ttyUSB0 2>/dev/null || true
python3 -m serial.tools.list_ports -v 2>/dev/null || true

echo
echo "== processes using /dev/ttyUSB0 =="
fuser -v /dev/ttyUSB0 2>&1 || true

echo
echo "== kernel log =="
dmesg | tail -80 | grep -Ei "ttyUSB|ch34|ch341|usb|brltty" || true

echo
echo "== raw serial scan with Arduino-style reset =="
./scripts/sklad_serial_sensor_bridge.py \
  --port "$PORT" \
  --device-id "$DEVICE_ID" \
  --scan-lines \
  --sniff-seconds 5 \
  --arduino-reset \
  --warmup-seconds 2 || true

echo
echo "== common command probes at 19200 =="
for command in '?' READ read GET DHT; do
  echo "-- command: $command"
  ./scripts/sklad_serial_sensor_bridge.py \
    --port "$PORT" \
    --baud 19200 \
    --device-id "$DEVICE_ID" \
    --sniff-raw \
    --sniff-seconds 3 \
    --arduino-reset \
    --warmup-seconds 2 \
    --write-command "$command" \
    --line-ending lf || true
done

echo
echo "== Modbus safe read scan =="
./scripts/sklad_serial_sensor_bridge.py \
  --port "$PORT" \
  --baud 9600 \
  --device-id "$DEVICE_ID" \
  --scan-modbus \
  --scan-raw \
  --modbus-timeout 0.3 || true
