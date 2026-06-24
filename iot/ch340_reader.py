#!/usr/bin/env python3
"""
CH340 USB-to-serial sensor bridge for warehouse storage conditions.

Reads lines from a serial port and POSTs temperature/humidity readings
to the sklad API at /api/v1/sensor-readings.

Supports multiple common Arduino sketch output formats:
  - CSV:    T:23.5,H:45.2  or  23.5,45.2  or  temp:23.5,hum:45.2
  - JSON:   {"temp":23.5,"hum":45.2}
  - Space:  23.5 45.2
  - Verbose: Temperature: 23.5 C, Humidity: 45.2 %

Configuration via environment variables (or .env file next to this script):
  CH340_PORT        Serial port, default /dev/ttyUSB0
  CH340_BAUD        Baud rate,   default 9600
  CH340_DEVICE_ID   Sklad sensor device ID (required)
  CH340_API_URL     API base URL, default http://localhost:8120/api/v1
  CH340_API_TOKEN   Bearer token for API auth (if auth enabled)
  CH340_INTERVAL    Min seconds between readings, default 30
  CH340_TEMP_FIELD  Override field name in JSON output (default: auto-detect)
  CH340_HUM_FIELD   Override field name in JSON output (default: auto-detect)
  CH340_VERBOSE     Set 1 to log raw bytes for diagnostics
"""

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

# ── configuration ────────────────────────────────────────────────────────────
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)

_load_dotenv(Path(__file__).parent / ".env.iot")
_load_dotenv(Path(__file__).parent.parent / ".env")

PORT        = os.environ.get("CH340_PORT", "/dev/ttyUSB0")
BAUD        = int(os.environ.get("CH340_BAUD", "9600"))
DEVICE_ID   = os.environ.get("CH340_DEVICE_ID", "")
API_URL     = os.environ.get("CH340_API_URL", "http://localhost:8120/api/v1")
API_TOKEN   = os.environ.get("CH340_API_TOKEN", "")
INTERVAL    = int(os.environ.get("CH340_INTERVAL", "30"))
TEMP_FIELD  = os.environ.get("CH340_TEMP_FIELD", "")
HUM_FIELD   = os.environ.get("CH340_HUM_FIELD", "")
VERBOSE     = os.environ.get("CH340_VERBOSE", "0") == "1"

logging.basicConfig(
    level=logging.DEBUG if VERBOSE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ch340")

# ── format parsers ───────────────────────────────────────────────────────────
def _try_json(line: str):
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    temp_keys = [TEMP_FIELD] if TEMP_FIELD else ["temp", "temperature", "t", "T", "Temperature"]
    hum_keys  = [HUM_FIELD]  if HUM_FIELD  else ["hum",  "humidity",    "h", "H", "Humidity", "rh"]
    temp = next((float(data[k]) for k in temp_keys if k in data), None)
    hum  = next((float(data[k]) for k in hum_keys  if k in data), None)
    return (temp, hum)


def _try_labeled_csv(line: str):
    """T:23.5,H:45.2 | temp:23.5,hum:45.2 | Temperature:23.5,Humidity:45.2"""
    temp_re = re.search(r"(?:temp(?:erature)?|t)\s*[:=]\s*([+-]?\d+\.?\d*)", line, re.IGNORECASE)
    hum_re  = re.search(r"(?:hum(?:idity)?|h|rh)\s*[:=]\s*([+-]?\d+\.?\d*)", line, re.IGNORECASE)
    if temp_re and hum_re:
        return float(temp_re.group(1)), float(hum_re.group(1))
    return None


def _try_plain_csv(line: str):
    """23.5,45.2 or 23.5 45.2"""
    parts = re.split(r"[,\s]+", line.strip())
    nums = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            pass
    if len(nums) >= 2:
        return nums[0], nums[1]
    return None


def _try_verbose(line: str):
    """Temperature: 23.5 C, Humidity: 45.2 %"""
    temp_re = re.search(r"temp(?:erature)?\s*[:=]?\s*([+-]?\d+\.?\d*)\s*[cC°]?", line, re.IGNORECASE)
    hum_re  = re.search(r"hum(?:idity)?\s*[:=]?\s*([+-]?\d+\.?\d*)\s*%?", line, re.IGNORECASE)
    if temp_re and hum_re:
        return float(temp_re.group(1)), float(hum_re.group(1))
    return None


def parse_line(line: str):
    """Return (temp, hum) or None. Tries parsers in priority order."""
    for parser in [_try_json, _try_labeled_csv, _try_verbose, _try_plain_csv]:
        result = parser(line)
        if result is not None:
            temp, hum = result
            if -40 <= temp <= 125 and 0 <= hum <= 100:
                return temp, hum
            log.debug("Out-of-range values: temp=%s hum=%s (raw: %r)", temp, hum, line)
    return None


# ── API client ───────────────────────────────────────────────────────────────
def _headers():
    h = {"Content-Type": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def post_reading(temp: float, hum: float) -> bool:
    import urllib.request
    payload = json.dumps({
        "device_id": int(DEVICE_ID),
        "temperature": temp,
        "humidity": hum,
    }).encode()
    url = f"{API_URL.rstrip('/')}/sensor-readings"
    req = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                log.info("Posted: temp=%.1f hum=%.1f → %s", temp, hum, resp.status)
                return True
            log.warning("API returned %s", resp.status)
    except Exception as exc:
        log.error("API error: %s", exc)
    return False


# ── main loop ────────────────────────────────────────────────────────────────
def run():
    if not DEVICE_ID:
        log.error("CH340_DEVICE_ID not set. Create a sensor device in the UI first, then set its ID here.")
        sys.exit(1)

    try:
        import serial  # pyserial
    except ImportError:
        log.error("pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    log.info("Opening %s @ %d baud (device_id=%s, interval=%ds)", PORT, BAUD, DEVICE_ID, INTERVAL)

    last_posted = 0.0
    consecutive_errors = 0

    while True:
        try:
            with serial.Serial(PORT, BAUD, timeout=5) as ser:
                log.info("Serial port open")
                consecutive_errors = 0
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if VERBOSE:
                        log.debug("RAW: %r", line)
                    if not line:
                        continue

                    result = parse_line(line)
                    if result is None:
                        log.debug("Unrecognized format: %r", line)
                        continue

                    temp, hum = result
                    now = time.time()
                    if now - last_posted < INTERVAL:
                        log.debug("Throttled (%.0fs < %ds)", now - last_posted, INTERVAL)
                        continue

                    if post_reading(temp, hum):
                        last_posted = now

        except Exception as exc:
            consecutive_errors += 1
            wait = min(60 * consecutive_errors, 300)
            log.error("Serial error (%d): %s — retry in %ds", consecutive_errors, exc, wait)
            time.sleep(wait)


if __name__ == "__main__":
    run()
