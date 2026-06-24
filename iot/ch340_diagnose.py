#!/usr/bin/env python3
"""
Diagnostic tool for CH340 sensor — use this to identify baud rate and data format
before configuring the bridge.

Usage:
  python3 ch340_diagnose.py [port] [baud]

Examples:
  python3 ch340_diagnose.py                        # auto-scan common ports and bauds
  python3 ch340_diagnose.py /dev/ttyUSB0 9600      # test specific config
  python3 ch340_diagnose.py /dev/ttyUSB0 115200
"""

import sys
import time

COMMON_PORTS = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]
COMMON_BAUDS = [9600, 115200, 57600, 38400, 19200, 4800]

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial not installed. Run: pip install pyserial")
    sys.exit(1)


def probe(port: str, baud: int, seconds: int = 3):
    print(f"\n── {port} @ {baud} ──")
    try:
        with serial.Serial(port, baud, timeout=1) as ser:
            print(f"  Opened. Reading {seconds}s of data...")
            deadline = time.time() + seconds
            lines = []
            while time.time() < deadline:
                raw = ser.readline()
                if raw:
                    try:
                        decoded = raw.decode("utf-8").rstrip()
                    except UnicodeDecodeError:
                        decoded = f"<binary: {raw.hex()}>"
                    lines.append(decoded)
                    print(f"  > {decoded!r}")
            if not lines:
                print("  (no data received)")
    except serial.SerialException as e:
        print(f"  Error: {e}")


def auto_scan():
    detected = [p.device for p in serial.tools.list_ports.comports()]
    if detected:
        print("Detected serial ports:", detected)
    else:
        print("No serial ports detected by OS. Trying common paths...")
        detected = COMMON_PORTS

    port_arg = sys.argv[1] if len(sys.argv) > 1 else None
    baud_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if port_arg and baud_arg:
        probe(port_arg, baud_arg, seconds=5)
    elif port_arg:
        for baud in COMMON_BAUDS:
            probe(port_arg, baud)
    else:
        for port in detected:
            for baud in COMMON_BAUDS[:2]:  # just 9600 and 115200 in auto mode
                probe(port, baud)


if __name__ == "__main__":
    auto_scan()
