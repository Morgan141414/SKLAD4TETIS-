#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import select
import struct
import sys
import termios
import time
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any


BAUDS = {
    1200: termios.B1200,
    2400: termios.B2400,
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


COMMON_MODBUS_BAUDS = (9600, 4800, 19200, 38400, 115200)
COMMON_MODBUS_SLAVES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 247)
COMMON_MODBUS_STARTS = (0, 1, 2, 3, 4, 16, 256)
COMMON_MODBUS_FUNCTIONS = (3, 4)
COMMON_MODBUS_PARITIES = ("N", "E", "O")
TIOCMBIS = 0x5416
TIOCMBIC = 0x5417
TIOCM_DTR = 0x002
TIOCM_RTS = 0x004


def configure_serial(fd: int, baud: int, parity: str = "N") -> None:
    if baud not in BAUDS:
        raise SystemExit(f"Unsupported baud rate: {baud}")
    parity = parity.upper()
    if parity not in {"N", "E", "O"}:
        raise SystemExit("Parity must be one of: N, E, O")
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    if parity == "E":
        attrs[2] |= termios.PARENB
        attrs[2] &= ~termios.PARODD
    elif parity == "O":
        attrs[2] |= termios.PARENB
        attrs[2] |= termios.PARODD
    else:
        attrs[2] &= ~termios.PARENB
    attrs[3] = 0
    attrs[4] = BAUDS[baud]
    attrs[5] = BAUDS[baud]
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def set_modem_line(fd: int, line: int, enabled: bool) -> None:
    request = TIOCMBIS if enabled else TIOCMBIC
    fcntl.ioctl(fd, request, struct.pack("I", line))


def apply_serial_monitor_controls(fd: int, args: argparse.Namespace) -> None:
    if args.arduino_reset:
        set_modem_line(fd, TIOCM_DTR, False)
        set_modem_line(fd, TIOCM_RTS, False)
        time.sleep(args.reset_seconds)
        set_modem_line(fd, TIOCM_DTR, True)
        set_modem_line(fd, TIOCM_RTS, True)
    else:
        if args.dtr is not None:
            set_modem_line(fd, TIOCM_DTR, args.dtr == "on")
        if args.rts is not None:
            set_modem_line(fd, TIOCM_RTS, args.rts == "on")
    if args.warmup_seconds > 0:
        time.sleep(args.warmup_seconds)
    try:
        os.read(fd, 4096)
    except BlockingIOError:
        pass


def parse_reading(line: str) -> dict[str, str] | None:
    clean = line.strip()
    if not clean:
        return None
    try:
        payload = json.loads(clean)
        temperature = payload.get("temperature_c", payload.get("temperature", payload.get("temp")))
        humidity = payload.get("humidity_percent", payload.get("humidity", payload.get("hum")))
        return normalize_values(temperature, humidity)
    except json.JSONDecodeError:
        pass

    labeled = dict(
        (match.group("key").lower(), match.group("value"))
        for match in re.finditer(
            r"(?P<key>temp(?:erature)?|t|humidity|hum|h)\s*[:=]\s*(?P<value>-?\d+(?:[.,]\d+)?)",
            clean,
            flags=re.IGNORECASE,
        )
    )
    if labeled:
        temperature = labeled.get("temperature") or labeled.get("temp") or labeled.get("t")
        humidity = labeled.get("humidity") or labeled.get("hum") or labeled.get("h")
        return normalize_values(temperature, humidity)

    parts = [part.strip() for part in re.split(r"[;,\s]+", clean) if part.strip()]
    if len(parts) >= 2:
        return normalize_values(parts[0], parts[1])
    return None


def normalize_values(temperature: Any, humidity: Any) -> dict[str, str] | None:
    reading: dict[str, str] = {}
    if temperature is not None:
        reading["temperature_c"] = str(Decimal(str(temperature).replace(",", ".")))
    if humidity is not None:
        reading["humidity_percent"] = str(Decimal(str(humidity).replace(",", ".")))
    return reading or None


def post_reading(api_base: str, token: str | None, device_id: int, reading: dict[str, str], raw: str) -> None:
    payload = {
        "device_id": device_id,
        "temperature_c": reading.get("temperature_c"),
        "humidity_percent": reading.get("humidity_percent"),
        "raw_payload": raw.strip()[:2000],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_base.rstrip("/") + "/api/v1/sensor-readings",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def line_ending(value: str) -> bytes:
    if value == "none":
        return b""
    if value == "lf":
        return b"\n"
    if value == "cr":
        return b"\r"
    if value == "crlf":
        return b"\r\n"
    raise SystemExit("Line ending must be one of: none, lf, cr, crlf")


def write_command_if_needed(fd: int, args: argparse.Namespace) -> None:
    if args.write_command is None:
        return
    command = args.write_command.encode(args.encoding) + line_ending(args.line_ending)
    os.write(fd, command)
    if args.write_delay_seconds > 0:
        time.sleep(args.write_delay_seconds)


def modbus_crc(frame: bytes) -> int:
    crc = 0xFFFF
    for byte in frame:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def modbus_frame(payload: bytes) -> bytes:
    crc = modbus_crc(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def read_serial_available(fd: int, timeout: float) -> bytes:
    end = time.time() + timeout
    chunks: list[bytes] = []
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], max(0.0, min(0.05, end - time.time())))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 512)
        except BlockingIOError:
            continue
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


def modbus_read_registers(
    fd: int,
    *,
    slave: int,
    function: int,
    start: int,
    count: int,
    timeout: float,
) -> list[int] | None:
    registers = modbus_read_registers_raw(
        fd,
        slave=slave,
        function=function,
        start=start,
        count=count,
        timeout=timeout,
    )
    if registers is None:
        return None
    return registers["values"]


def modbus_read_registers_raw(
    fd: int,
    *,
    slave: int,
    function: int,
    start: int,
    count: int,
    timeout: float,
) -> dict[str, Any] | None:
    if function not in {3, 4}:
        raise SystemExit("Modbus function must be 3 or 4")
    request = modbus_frame(
        bytes(
            (
                slave,
                function,
                (start >> 8) & 0xFF,
                start & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            )
        )
    )
    try:
        os.read(fd, 4096)
    except BlockingIOError:
        pass
    os.write(fd, request)
    response = read_serial_available(fd, timeout)
    expected_len = 5 + count * 2
    if len(response) < expected_len:
        return None
    for offset in range(0, len(response) - expected_len + 1):
        frame = response[offset : offset + expected_len]
        if frame[0] != slave or frame[1] != function or frame[2] != count * 2:
            continue
        body = frame[:-2]
        received_crc = frame[-2] | (frame[-1] << 8)
        if modbus_crc(body) != received_crc:
            continue
        values = []
        for index in range(count):
            value = (frame[3 + index * 2] << 8) | frame[4 + index * 2]
            values.append(value)
        return {"values": values, "frame_hex": frame.hex(" ")}
    return None


def signed_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def modbus_values_to_reading(
    values: list[int],
    *,
    temperature_index: int,
    humidity_index: int,
    scale: Decimal,
    signed_temperature: bool,
) -> dict[str, str] | None:
    if temperature_index >= len(values) and humidity_index >= len(values):
        return None
    temperature = None
    humidity = None
    if temperature_index < len(values):
        raw_temperature = values[temperature_index]
        if signed_temperature:
            raw_temperature = signed_16(raw_temperature)
        temperature = Decimal(raw_temperature) / scale
    if humidity_index < len(values):
        humidity = Decimal(values[humidity_index]) / scale
    return normalize_values(temperature, humidity)


def plausible_reading(reading: dict[str, str]) -> bool:
    temperature = Decimal(reading.get("temperature_c", "0"))
    humidity = Decimal(reading.get("humidity_percent", "0"))
    return Decimal("-50") <= temperature <= Decimal("100") and Decimal("0") <= humidity <= Decimal("100")


def scan_modbus(args: argparse.Namespace) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    bauds = [args.baud] if args.baud else list(COMMON_MODBUS_BAUDS)
    slaves = [args.modbus_slave] if args.modbus_slave else list(COMMON_MODBUS_SLAVES)
    starts = sorted({args.modbus_register, *COMMON_MODBUS_STARTS})
    parities = [args.parity.upper()] if args.parity else list(COMMON_MODBUS_PARITIES)
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        for baud in bauds:
            for parity in parities:
                configure_serial(fd, baud, parity)
                for slave in slaves:
                    for function in COMMON_MODBUS_FUNCTIONS:
                        for start in starts:
                            result = modbus_read_registers_raw(
                                fd,
                                slave=slave,
                                function=function,
                                start=start,
                                count=args.modbus_registers,
                                timeout=args.modbus_timeout,
                            )
                            if result is None:
                                continue
                            values = result["values"]
                            candidates: list[dict[str, Any]] = []
                            for temperature_index, humidity_index in ((1, 0), (0, 1)):
                                reading = modbus_values_to_reading(
                                    values,
                                    temperature_index=temperature_index,
                                    humidity_index=humidity_index,
                                    scale=Decimal(str(args.modbus_scale)),
                                    signed_temperature=args.modbus_signed_temperature,
                                )
                                if reading and plausible_reading(reading):
                                    candidates.append(
                                        {
                                            "temperature_index": temperature_index,
                                            "humidity_index": humidity_index,
                                            **reading,
                                        }
                                    )
                            if args.scan_raw or candidates:
                                item: dict[str, Any] = {
                                    "baud": baud,
                                    "parity": parity,
                                    "slave": slave,
                                    "function": function,
                                    "start": start,
                                    "registers": values,
                                    "frame_hex": result["frame_hex"],
                                }
                                if candidates:
                                    item.update(candidates[0])
                                found.append(item)
                            if candidates:
                                continue
                            for scale in (Decimal("1"), Decimal("10"), Decimal("100")):
                                for temperature_index, humidity_index in ((1, 0), (0, 1)):
                                    reading = modbus_values_to_reading(
                                        values,
                                        temperature_index=temperature_index,
                                        humidity_index=humidity_index,
                                        scale=scale,
                                        signed_temperature=args.modbus_signed_temperature,
                                    )
                                    if reading and plausible_reading(reading):
                                        found.append(
                                            {
                                                "baud": baud,
                                                "parity": parity,
                                                "slave": slave,
                                                "function": function,
                                                "start": start,
                                                "registers": values,
                                                "frame_hex": result["frame_hex"],
                                                "scale": str(scale),
                                                "temperature_index": temperature_index,
                                                "humidity_index": humidity_index,
                                                **reading,
                                            }
                                        )
                            if not args.scan_raw:
                                continue
                            reading = modbus_values_to_reading(
                                values,
                                temperature_index=args.temperature_index,
                                humidity_index=args.humidity_index,
                                scale=Decimal(str(args.modbus_scale)),
                                signed_temperature=args.modbus_signed_temperature,
                            )
        return found
    finally:
        os.close(fd)


def handle_reading(args: argparse.Namespace, token: str | None, reading: dict[str, str], raw: str) -> None:
    if args.dry_run:
        print(json.dumps({"device_id": args.device_id, **reading, "raw": raw}, ensure_ascii=False))
        return
    try:
        post_reading(args.api, token, args.device_id, reading, raw)
        print(json.dumps({"sent": True, "device_id": args.device_id, **reading}, ensure_ascii=False))
    except urllib.error.URLError as error:
        print(f"post failed: {error}", file=sys.stderr)
        time.sleep(args.retry_seconds)


def run_lines(args: argparse.Namespace, token: str | None) -> None:
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure_serial(fd, args.baud, args.parity)
        apply_serial_monitor_controls(fd, args)
        write_command_if_needed(fd, args)
        buffer = b""
        while True:
            ready, _, _ = select.select([fd], [], [], args.poll_seconds)
            if not ready:
                if args.once:
                    return
                continue
            chunk = os.read(fd, 512)
            if not chunk:
                if args.once:
                    return
                continue
            buffer += chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.decode(args.encoding, errors="replace")
                reading = parse_reading(line)
                if reading is None:
                    print(f"skip: {line.strip()}", file=sys.stderr)
                    continue
                handle_reading(args, token, reading, line.strip())
                if args.once:
                    return
    finally:
        os.close(fd)


def run_modbus(args: argparse.Namespace, token: str | None) -> None:
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure_serial(fd, args.baud, args.parity)
        apply_serial_monitor_controls(fd, args)
        while True:
            values = modbus_read_registers(
                fd,
                slave=args.modbus_slave,
                function=args.modbus_function,
                start=args.modbus_register,
                count=args.modbus_registers,
                timeout=args.modbus_timeout,
            )
            if values is None:
                print("modbus: no response", file=sys.stderr)
                if args.once:
                    return
                time.sleep(args.poll_seconds)
                continue
            reading = modbus_values_to_reading(
                values,
                temperature_index=args.temperature_index,
                humidity_index=args.humidity_index,
                scale=Decimal(str(args.modbus_scale)),
                signed_temperature=args.modbus_signed_temperature,
            )
            if reading is None:
                print(f"modbus: cannot map registers {values}", file=sys.stderr)
            else:
                handle_reading(args, token, reading, json.dumps({"modbus_registers": values}))
            if args.once:
                return
            time.sleep(args.poll_seconds)
    finally:
        os.close(fd)


def run_sniff_raw(args: argparse.Namespace) -> None:
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure_serial(fd, args.baud, args.parity)
        apply_serial_monitor_controls(fd, args)
        write_command_if_needed(fd, args)
        end = time.time() + args.sniff_seconds
        while time.time() < end:
            chunk = read_serial_available(fd, min(0.25, max(0.01, end - time.time())))
            if not chunk:
                continue
            text = chunk.decode(args.encoding, errors="replace")
            print(json.dumps({"hex": chunk.hex(" "), "text": text}, ensure_ascii=False))
    finally:
        os.close(fd)


def scan_lines(args: argparse.Namespace) -> None:
    bauds = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
    for baud in bauds:
        args.baud = baud
        print(f"scan-lines: baud={baud}", file=sys.stderr)
        fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            configure_serial(fd, baud, args.parity)
            apply_serial_monitor_controls(fd, args)
            write_command_if_needed(fd, args)
            data = read_serial_available(fd, args.sniff_seconds)
            if data:
                print(
                    json.dumps(
                        {
                            "baud": baud,
                            "hex": data.hex(" "),
                            "text": data.decode(args.encoding, errors="replace"),
                        },
                        ensure_ascii=False,
                    )
                )
                return
        finally:
            os.close(fd)
    print("scan-lines: no serial bytes received", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    token = args.token or os.getenv("SKLAD_API_TOKEN")
    if args.sniff_raw:
        run_sniff_raw(args)
        return
    if args.scan_lines:
        scan_lines(args)
        return
    if args.scan_modbus:
        found = scan_modbus(args)
        for item in found:
            print(json.dumps(item, ensure_ascii=False))
        if not found:
            print("modbus scan: no plausible temperature/humidity response", file=sys.stderr)
        return
    if args.protocol == "modbus-rtu":
        run_modbus(args, token)
        return
    run_lines(args, token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge a USB serial temperature/humidity sensor to SKLAD API.")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--parity", choices=("N", "E", "O", "n", "e", "o"), default="N")
    parser.add_argument("--api", default="http://127.0.0.1:8120")
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--token", default=None)
    parser.add_argument("--protocol", choices=("lines", "modbus-rtu"), default="lines")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--retry-seconds", type=float, default=5.0)
    parser.add_argument("--warmup-seconds", type=float, default=2.0)
    parser.add_argument("--arduino-reset", action="store_true")
    parser.add_argument("--reset-seconds", type=float, default=0.25)
    parser.add_argument("--dtr", choices=("on", "off"), default=None)
    parser.add_argument("--rts", choices=("on", "off"), default=None)
    parser.add_argument("--write-command", default=None)
    parser.add_argument("--write-delay-seconds", type=float, default=0.2)
    parser.add_argument("--line-ending", choices=("none", "lf", "cr", "crlf"), default="lf")
    parser.add_argument("--sniff-raw", action="store_true")
    parser.add_argument("--sniff-seconds", type=float, default=5.0)
    parser.add_argument("--scan-lines", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scan-modbus", action="store_true")
    parser.add_argument("--scan-raw", action="store_true")
    parser.add_argument("--modbus-slave", type=int, default=1)
    parser.add_argument("--modbus-function", type=int, default=3)
    parser.add_argument("--modbus-register", type=int, default=0)
    parser.add_argument("--modbus-registers", type=int, default=2)
    parser.add_argument("--modbus-timeout", type=float, default=0.4)
    parser.add_argument("--modbus-scale", default="10")
    parser.add_argument("--temperature-index", type=int, default=1)
    parser.add_argument("--humidity-index", type=int, default=0)
    parser.add_argument("--modbus-signed-temperature", action="store_true", default=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
