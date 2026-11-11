#!/usr/bin/env python3
"""catch_hello.py - force a fresh Sahara HELLO and catch it at the instant the port appears.

Why a separate tool
-------------------
Sahara emits exactly one HELLO per reset, and whoever opens the port first
consumes it. Opening a port that has been idle for hours therefore yields
silence - not a fault, just an expired packet. docs/25-com-world-works.md showed
the vendor tool receiving a genuine HELLO on COM10, so the port is correct; the
open question is only *when* to open.

This tool answers that by opening the port as fast as it appears, polling the
device list at 5 ms instead of seconds. It reports the exact delay between
"port listed" and "first byte", which is the number that decides whether a
custom client can ever win this - and therefore whether the region ordering
that DDR_DATA.BIN needs is reachable at all.

Read-only: it opens the port, reads, and closes. It can optionally send
SAHARA_RESET (0x07 - never 0x13) to provoke a fresh HELLO.

Usage
    python catch_hello.py --port COM10 --seconds 20
    python catch_hello.py --port COM10 --reset        # provoke, then catch
"""
from __future__ import annotations

import argparse
import struct
import sys
import threading
import time

import serial
import serial.tools.list_ports

CMD_HELLO_REQ = 0x01
CMD_RESET = 0x07
CMD_RESET_RSP = 0x08

T0 = time.time()


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {msg}", flush=True)


def present(port: str) -> bool:
    return any(p.device.upper() == port.upper() for p in serial.tools.list_ports.comports())


def reset_device(port: str) -> bool:
    """Open, send SAHARA_RESET, close. Provokes one fresh HELLO on re-enumeration."""
    try:
        with serial.Serial(port, 115200, timeout=0.5, write_timeout=1.0) as s:
            s.write(struct.pack("<II", CMD_RESET, 8))
            s.flush()
        log("  SAHARA_RESET sent")
        return True
    except Exception as err:  # noqa: BLE001
        log(f"  reset failed: {type(err).__name__}: {err}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--reset", action="store_true", help="provoke a fresh HELLO first")
    ap.add_argument("--watch", action="store_true",
                    help="wait for the port to leave the bus and come back (physical power cycle)")
    ap.add_argument("--watch-timeout", type=float, default=300.0)
    args = ap.parse_args()

    port = args.port.upper()

    # Order matters: provoke first, then watch. Reversing these makes --watch wait
    # for a power cycle that --reset was supposed to cause.
    if args.reset:
        if not present(port):
            t = time.time() + 30
            while time.time() < t and not present(port):
                time.sleep(0.02)
        if present(port):
            reset_device(port)

    if args.watch:
        # A cold start is the only way to obtain a HELLO once the previous one has
        # been consumed: Sahara emits exactly one per boot. Wait for the node to go
        # away, then open the port the instant it returns.
        log(f"  watching {port}: waiting for it to LEAVE the bus (power cycle now)")
        deadline = time.time() + args.watch_timeout
        left = False
        while time.time() < deadline:
            if not present(port):
                left = True
                log(f"  GONE from the bus at t={time.time() - T0:.2f}s - watching for its return")
                break
            time.sleep(0.01)
        if not left:
            log("  port never left the bus; no power cycle was seen")
            return 1

        back_deadline = time.time() + args.watch_timeout
        while time.time() < back_deadline and not present(port):
            time.sleep(0.002)
        if not present(port):
            log("  port never came back")
            return 1
        log(f"  BACK at t={time.time() - T0:.2f}s - opening immediately")
        # fall through to the race below without re-checking or resetting

    if not present(port):
        log(f"  {port} not present - waiting for it")
        t = time.time() + 60
        while time.time() < t and not present(port):
            time.sleep(0.02)
        if not present(port):
            log(f"  {port} never appeared")
            return 1

    # ---- the actual race: open the moment the port is listed ----
    log(f"  port listed at t={time.time() - T0:.3f}s - opening and reading now")
    result = {"data": b"", "delay": None, "err": None}

    def reader() -> None:
        # Windows lists the port a moment before the driver finishes creating it,
        # so an immediate open fails with "device does not exist" (433). Retry for a
        # short window: the HELLO is waiting on the other side of the open, not
        # behind a delay, so this loses nothing.
        s = None
        err_last = None
        open_deadline = time.time() + 3.0
        while time.time() < open_deadline:
            try:
                s = serial.Serial(port, 115200, timeout=0.05, write_timeout=1.0)
                break
            except Exception as err:  # noqa: BLE001
                err_last = f"open: {type(err).__name__}: {err}"
                time.sleep(0.003)
        if s is None:
            result["err"] = err_last
            return
        opened = time.time()
        result["open_ms"] = (opened - T0) * 1000
        buf = b""
        try:
            deadline = opened + args.seconds
            while time.time() < deadline:
                try:
                    chunk = s.read(512)
                except Exception as err:  # noqa: BLE001
                    result["err"] = f"read: {type(err).__name__}: {err}"
                    break
                if chunk:
                    if not buf:
                        result["delay"] = time.time() - opened
                    buf += chunk
                    if len(buf) >= 8:
                        break
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        result["data"] = buf

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    th.join(timeout=args.seconds + 5)

    data = result["data"]
    log("")
    if data:
        log(f"  GOT {len(data)} bytes, first byte after {result['delay'] * 1000:.0f} ms")
        log(f"  hex: {data[:64].hex(' ')}")
        if len(data) >= 8:
            cmd, ln = struct.unpack_from("<II", data, 0)
            names = {0x01: "HELLO_REQ", 0x02: "HELLO_RSP", 0x04: "END_TRANSFER",
                     0x08: "RESET_RSP", 0x09: "MEMORY_DEBUG", 0x10: "MEMORY_DEBUG_64"}
            log(f"  cmd={cmd:#x} ({names.get(cmd, 'other')}) len={ln}")
            if cmd == CMD_HELLO_REQ and ln >= 0x30:
                ver, mode = struct.unpack_from("<I", data, 8)[0], struct.unpack_from("<I", data, 20)[0]
                log(f"  HELLO ver={ver} mode={mode}"
                    f"{'  <- MEMORY_DEBUG, exactly what we need' if mode == 2 else ''}")
        return 0

    log(f"  no bytes. err={result['err']}")
    log("  => either the HELLO was emitted before the port could be opened,")
    log("     or this device does not re-emit one without a fresh boot.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
