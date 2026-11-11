#!/usr/bin/env python3
"""hold_and_catch.py - keep ONE handle on the port across a real power cycle.

Why the previous catchers missed the packet
-------------------------------------------
Every one of them opened, waited a few seconds, closed, and reopened. Between
those cycles the CDC driver tears the pipe down, and any packet already sitting
in it is discarded with the handle. Opening and closing is not free: it is the
same act as reading, as far as a buffered packet is concerned.

The vendor tool's log proves the packet is readable - it took a full HELLO_REQ
~18 s after the port appeared - so the data is there. What differs is that it
opens once and keeps the handle.

So this tool:

  * opens the port once and HOLDS it;
  * reads continuously, with no reopen in the normal path;
  * when the handle dies (error 995 - the device re-enumerating), it reopens in
    a tight loop for several seconds, because that is the moment the fresh
    HELLO can be taken;
  * never writes, except the protocol replies that a HELLO requires.

Read-only in the sense that matters: no SAHARA_RESET, no upload, no storage
command. The only bytes written are HELLO_RSP/MEMORY_DEBUG, which a read session
cannot work without.

Usage
    python hold_and_catch.py --port COM10 --seconds 150
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

sys.path.insert(0, str(Path(__file__).resolve().parent))

from com_sahara_client import (  # noqa: E402
    CMD_HELLO_REQ, CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64, MODE_MEMORY_DEBUG,
    hello_rsp, parse_table, print_table,
)

OUT = Path(__file__).resolve().parent / "ddr_data_grab"
T0 = time.time()


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {m}", flush=True)


def present(port: str) -> bool:
    try:
        return any(p.device.upper() == port.upper()
                   for p in serial.tools.list_ports.comports())
    except Exception:  # noqa: BLE001
        return False


class Held:
    """A port handle that survives re-enumeration by being replaced immediately."""

    def __init__(self, port: str) -> None:
        self.port = port
        self.ser: serial.Serial | None = None
        self.buf = b""
        self.deaths = 0

    def connect(self, budget: float = 30.0) -> bool:
        end = time.time() + budget
        while time.time() < end:
            try:
                self.ser = serial.Serial(self.port, 115200, timeout=0.05,
                                         write_timeout=2.0)
                self.buf = b""
                log(f"  handle open (death #{self.deaths})")
                return True
            except Exception:  # noqa: BLE001
                time.sleep(0.003)
        return False

    def read(self, n: int) -> bytes:
        if self.ser is None:
            return b""
        try:
            return self.ser.read(n)
        except Exception as err:  # noqa: BLE001
            self.deaths += 1
            log(f"  handle died ({type(err).__name__}) - device re-enumerated")
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.ser = None
            self.buf = b""
            return b""

    def write(self, data: bytes) -> bool:
        if self.ser is None:
            return False
        try:
            self.ser.write(data)
            self.ser.flush()
            return True
        except Exception as err:  # noqa: BLE001
            log(f"  write failed: {type(err).__name__}")
            return False

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.ser = None


def packet(held: Held, timeout: float):
    deadline = time.time() + timeout
    while len(held.buf) < 8:
        if time.time() > deadline:
            return None
        if held.ser is None:
            return None
        held.buf += held.read(64)
    cmd, ln = struct.unpack_from("<II", held.buf, 0)
    if ln < 8 or ln > (1 << 20):
        log(f"  bad framing cmd={cmd:#x} len={ln}")
        held.buf = b""
        return None
    while len(held.buf) < ln:
        if time.time() > deadline or held.ser is None:
            return None
        held.buf += held.read(4096)
    pkt, held.buf = held.buf[:ln], held.buf[ln:]
    return pkt


def raw_read(held: Held, length: int, timeout: float = 25.0) -> bytes:
    got = bytearray()
    deadline = time.time() + timeout
    while len(got) < length and time.time() < deadline:
        if held.ser is None:
            break
        chunk = held.read(min(65536, length - len(got)))
        if chunk:
            got += chunk
            deadline = time.time() + timeout
    return bytes(got)


def arm_hard_exit(seconds: float) -> None:
    """Guarantee the process dies, even if a loop is wedged.

    A catcher that outlives its budget still holds the COM handle, and an
    abandoned handle makes every later session fail with "access denied" or a
    mute port - the trap recorded in docs/07 F1. The port was in fact left
    claimed once during this session and had to be freed by hand. A timer thread
    makes that impossible regardless of what the loops are doing.
    """
    import threading

    def _expire() -> None:
        log(f"  hard deadline {seconds:.0f}s reached - exiting to release the port")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            # os._exit, not sys.exit: a blocked read in a C extension will not
            # unwind through an exception, and unwinding is not the point - the
            # point is that the handle is released now.
            import os
            os._exit(2)

    t = threading.Timer(seconds, _expire)
    t.daemon = True
    t.start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--seconds", type=float, default=150.0)
    args = ap.parse_args()
    port = args.port.upper()
    OUT.mkdir(exist_ok=True)
    end = time.time() + args.seconds
    arm_hard_exit(args.seconds + 20.0)

    log("=" * 74)
    log("#  hold_and_catch - one handle held across the power cycle")
    log("=" * 74)

    if not present(port):
        log(f"  {port} not present; waiting for it")
        while time.time() < end and not present(port):
            time.sleep(0.005)
        if not present(port):
            log("  never appeared")
            return 1

    held = Held(port)
    if not held.connect(20):
        log("  could not open")
        return 1

    log("  HOLDING the handle. RESET THE TABLET NOW (Power ~15 s, then power on).")

    # Main loop: keep reading until a HELLO arrives or the budget runs out.
    while time.time() < end:
        if held.ser is None:
            # the device went away: reconnect as fast as possible, because the
            # fresh HELLO can be waiting the instant the node returns.
            if not present(port):
                time.sleep(0.003)
                continue
            if not held.connect(15):
                log("  reconnect failed; continuing to watch")
                continue

        pkt = packet(held, 2.0)
        if pkt is None:
            continue

        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  packet cmd={cmd:#x} (not HELLO) - ignored")
            continue

        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} ***")
        if mode != MODE_MEMORY_DEBUG:
            log(f"  mode {mode} is not crashdump - not a memory session")
            continue

        held.buf = b""
        held.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = packet(held, 6.0)
        if rsp is None:
            log("  no MEMORY_DEBUG answer")
            continue
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
            log(f"  unexpected answer {rcmd:#x}")
            continue
        if rcmd == CMD_MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
        else:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
        log(f"  table @{tbl_addr:#x} len={tbl_len}")

        held.write(struct.pack("<IIQQ", 0x11, 24, tbl_addr, tbl_len))
        raw = raw_read(held, tbl_len, 12.0)
        log(f"  table bytes {len(raw)}")
        if not raw:
            continue
        (OUT / "memory_table_raw.bin").write_bytes(raw)
        tables = parse_table(raw)
        print_table(tables)

        for key in ("DDR_DATA", "SHRM_MEM"):
            for e in [t for t in tables
                      if key in (t["file"] or "").upper()
                      or key in (t["desc"] or "").upper()]:
                name = e["file"] or e["desc"]
                log("")
                log(f"  >>> reading {name}  {e['len']} B @ {e['addr']:#x}")
                if not held.write(struct.pack("<IIQQ", 0x11, 24, e["addr"], e["len"])):
                    break
                blob = raw_read(held, e["len"], 30.0)
                if blob:
                    fn = OUT / f"{e['addr']:#014x}_{name.replace('/', '_')}"
                    fn.write_bytes(blob)
                    nz = sum(1 for b in blob if b)
                    log(f"      {len(blob)}/{e['len']} B nonzero "
                        f"{nz / max(1, len(blob)):.1%} -> {fn.name}")
                    if key == "DDR_DATA" and len(blob) >= 20:
                        v = struct.unpack_from("<4I", blob, 4)
                        log(f"      *** DDR training data version {v[0]}.{v[1]}.{v[2]} ***")
                else:
                    log("      no data")
        log("")
        log(f"  artefacts in {OUT}")
        held.close()
        return 0

    log("  budget exhausted; no HELLO seen")
    held.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
