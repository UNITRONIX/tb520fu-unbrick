#!/usr/bin/env python3
"""grab_ddr_data.py - one process that waits for a cold boot, catches HELLO, reads DDR_DATA.

The problem this solves
-----------------------
Sahara emits exactly one HELLO per boot, and the first process to open the port
consumes it. Every previous attempt failed on that alone:

  * catch_hello.py opened the port, read the HELLO, then closed - so the HELLO was
    gone by the time the reader ran;
  * running the reader as a second step was therefore always one boot too late;
  * the vendor tool's 2026-11-11 11:02 log shows it did receive a genuine HELLO,
    so the port and the driver are correct. The difference was only *who opened
    first*.

So the catcher and the reader must be the same process, and it must already be
polling when the port returns.

What it does
------------
  1. wait for the port to LEAVE the bus (that is the reset being observed)
  2. wait for it to return, polling every 2 ms
  3. open it, retrying through the short window where Windows lists the port
     before the driver finishes creating it
  4. read the one HELLO, enter MEMORY_DEBUG, fetch the table
  5. read DDR_DATA first - before any multi-gigabyte window can be in the way
  6. also read SHRM_MEM, which carries the DDR firmware's own version and state

Read-only: MEMORY_DEBUG handshake and MEMORY_READ_64. No mode switch, no upload,
no storage write.

Usage
    python grab_ddr_data.py --port COM10 --wait 240
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
    CMD_CMD_READY, CMD_HELLO_REQ, CMD_HELLO_RSP, CMD_MEMORY_DEBUG,
    CMD_MEMORY_DEBUG_64, CMD_RESET, MODE_MEMORY_DEBUG, SerialLink, hello_rsp,
    mem_read, parse_table, print_table,
)

OUT = Path(__file__).resolve().parent / "ddr_data_grab"
T0 = time.time()


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {msg}", flush=True)


def present(port: str) -> bool:
    return any(p.device.upper() == port.upper()
               for p in serial.tools.list_ports.comports())


def open_now(port: str, budget: float = 4.0) -> SerialLink | None:
    """Open with retries: Windows lists the port slightly before it is usable."""
    deadline = time.time() + budget
    last = None
    while time.time() < deadline:
        try:
            return SerialLink(port, 115200)
        except Exception as err:  # noqa: BLE001
            last = f"{type(err).__name__}: {err}"
            time.sleep(0.002)
    log(f"  open failed after {budget:.1f}s: {last}")
    return None


def read_all(link: SerialLink):
    """HELLO -> MEMORY_DEBUG -> (table, raw). All inside the caller's session."""
    pkt = link.read_packet(4.0)
    if pkt is None:
        log("  no HELLO (the packet was consumed by whoever opened first)")
        return None, None
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO_REQ, got {cmd:#x}")
        return None, None

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  *** HELLO ver={ver} mode={mode} ***")
    if mode != MODE_MEMORY_DEBUG:
        log(f"  mode {mode} is not MEMORY_DEBUG - this is not a crashdump session")
        return None, None

    link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
    rsp = link.read_packet(6.0)
    if rsp is None:
        log("  no answer to HELLO_RSP")
        return None, None
    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
        log(f"  expected MEMORY_DEBUG, got {rcmd:#x}")
        return None, None

    if rcmd == CMD_MEMORY_DEBUG:
        tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
    else:
        tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
    log(f"  MEMORY_DEBUG: table @{tbl_addr:#x} len={tbl_len}")

    raw = mem_read(link, tbl_addr, tbl_len, tmo=10.0)
    log(f"  table received {len(raw)} B")
    return parse_table(raw), raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--wait", type=float, default=240.0,
                    help="how long to wait for the reset to be observed (s)")
    ap.add_argument("--no-watch", action="store_true",
                    help="skip waiting for the port to leave; use a port that is already up")
    args = ap.parse_args()

    port = args.port.upper()
    OUT.mkdir(exist_ok=True)

    log("=" * 74)
    log("#  grab_ddr_data - cold boot -> HELLO -> DDR_DATA, in one process")
    log("=" * 74)

    if not args.no_watch:
        if not present(port):
            log(f"  {port} not up yet; waiting for it to appear first")
            t = time.time() + 60
            while time.time() < t and not present(port):
                time.sleep(0.02)
            if not present(port):
                log("  port never appeared")
                return 1
        log(f"  {port} is up. RESET THE TABLET NOW (hold Power ~15 s, then power on)")
        log("  waiting for it to leave the bus...")

        deadline = time.time() + args.wait
        while time.time() < deadline and present(port):
            time.sleep(0.01)
        if present(port):
            log("  the port never left the bus - no reset was seen")
            return 1
        log(f"  GONE at t={time.time() - T0:.2f}s - polling for its return")

        while time.time() < deadline and not present(port):
            time.sleep(0.002)
        if not present(port):
            log("  port never came back")
            return 1
        log(f"  BACK at t={time.time() - T0:.2f}s - opening immediately")

    link = open_now(port)
    if link is None:
        return 1
    log("  port open")

    try:
        tables, raw = read_all(link)
        if tables is None:
            (OUT / "table_failed.txt").write_text(
                f"attempted {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            return 1

        (OUT / "memory_table_raw.bin").write_bytes(raw)
        print_table(tables)

        # DDR_DATA first, then SHRM_MEM. Order matters: DDR_DATA is the region the
        # vendor tool can never reach, and no 2 GiB window is read before it.
        wanted: list[dict] = []
        for key in ("DDR_DATA", "SHRM_MEM"):
            hit = [e for e in tables
                   if key in (e["file"] or "").upper() or key in (e["desc"] or "").upper()]
            wanted.extend(hit)
        if not wanted:
            log("  no DDR_DATA / SHRM_MEM entry in the table")
            return 1

        for e in wanted:
            name = e["file"] or e["desc"] or f"{e['addr']:#x}"
            log("")
            log(f"  reading {name}  {e['len']} B @ {e['addr']:#x}")
            blob = mem_read(link, e["addr"], e["len"], tmo=20.0)
            if blob:
                fn = OUT / f"{e['addr']:#014x}_{name.replace('/', '_')}"
                fn.write_bytes(blob)
                nz = sum(1 for b in blob if b)
                log(f"    {len(blob)}/{e['len']} B  nonzero {nz / max(1, len(blob)):.1%} -> {fn.name}")
                if name.upper().startswith("DDR_DATA") and len(blob) >= 20:
                    ver = struct.unpack_from("<4I", blob, 4)
                    log(f"    DDR training data version: {ver[0]}.{ver[1]}.{ver[2]}")
            else:
                log("    no data")
        log("")
        log(f"  artefacts in {OUT}")
        return 0
    finally:
        try:
            link.write(struct.pack("<II", CMD_RESET, 8))
            link.read_packet(1.5)
        except Exception:  # noqa: BLE001
            pass
        link.close()


if __name__ == "__main__":
    sys.exit(main())
