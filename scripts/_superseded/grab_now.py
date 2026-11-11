#!/usr/bin/env python3
"""grab_now.py - catch a HELLO on a port that is currently absent or present.

Used when the reset is already in progress, so there is no "port left the bus"
edge to wait for. It polls for the port to APPEAR, opens it the instant it does,
and does the whole MEMORY_DEBUG + DDR_DATA read inside that one session.

Same protocol code as com_sahara_client; this file only adds the timing logic.
Read-only.
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
    CMD_HELLO_REQ, CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64, CMD_RESET,
    MODE_MEMORY_DEBUG, SerialLink, hello_rsp, mem_read, parse_table, print_table,
)

OUT = Path(__file__).resolve().parent / "ddr_data_grab"
T0 = time.time()


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {m}", flush=True)


def present(port: str) -> bool:
    return any(p.device.upper() == port.upper()
               for p in serial.tools.list_ports.comports())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--budget", type=float, default=180.0)
    args = ap.parse_args()
    port = args.port.upper()
    OUT.mkdir(exist_ok=True)

    log("=" * 70)
    log(f"#  grab_now - waiting for {port} to appear, then reading in one session")
    log("=" * 70)

    deadline = time.time() + args.budget
    if present(port):
        log(f"  {port} is present already - opening now")
    else:
        log(f"  {port} absent - polling every 2 ms")
        while time.time() < deadline and not present(port):
            time.sleep(0.002)
        if not present(port):
            log("  port never appeared")
            return 1
        log(f"  APPEARED at t={time.time() - T0:.2f}s")

    link = None
    while time.time() < deadline and link is None:
        try:
            link = SerialLink(port, 115200)
        except Exception:  # noqa: BLE001
            if not present(port):
                log("  port vanished again while opening - resuming wait")
                while time.time() < deadline and not present(port):
                    time.sleep(0.002)
            time.sleep(0.002)
    if link is None:
        log("  could not open the port")
        return 1
    log("  port open - reading")

    try:
        pkt = link.read_packet(5.0)
        if pkt is None:
            log("  no HELLO in 5 s")
            return 1
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO_REQ, got {cmd:#x}")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} ***")
        if mode != MODE_MEMORY_DEBUG:
            log(f"  mode {mode} is not crashdump; stopping")
            return 1

        link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = link.read_packet(6.0)
        if rsp is None:
            log("  no MEMORY_DEBUG answer")
            return 1
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
            log(f"  unexpected {rcmd:#x}")
            return 1
        if rcmd == CMD_MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
        else:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
        log(f"  table @{tbl_addr:#x} len={tbl_len}")

        raw = mem_read(link, tbl_addr, tbl_len, tmo=10.0)
        log(f"  table bytes {len(raw)}")
        if not raw:
            return 1
        (OUT / "memory_table_raw.bin").write_bytes(raw)
        tables = parse_table(raw)
        print_table(tables)

        for key in ("DDR_DATA", "SHRM_MEM"):
            hits = [e for e in tables
                    if key in (e["file"] or "").upper()
                    or key in (e["desc"] or "").upper()]
            for e in hits:
                name = e["file"] or e["desc"]
                log("")
                log(f"  reading {name} {e['len']} B @ {e['addr']:#x}")
                blob = mem_read(link, e["addr"], e["len"], tmo=20.0)
                if blob:
                    fn = OUT / f"{e['addr']:#014x}_{name.replace('/', '_')}"
                    fn.write_bytes(blob)
                    nz = sum(1 for b in blob if b)
                    log(f"    {len(blob)}/{e['len']} B nonzero {nz/max(1,len(blob)):.1%} -> {fn.name}")
                    if key == "DDR_DATA" and len(blob) >= 20:
                        v = struct.unpack_from("<4I", blob, 4)
                        log(f"    DDR training data version {v[0]}.{v[1]}.{v[2]}")
                else:
                    log("    no data")
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
