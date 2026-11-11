#!/usr/bin/env python3
"""auto_grab.py - robust HELLO catcher: debounced open, handle-death recovery, one-session read.

Why the earlier attempts failed
-------------------------------
Measured on 2026-11-11: after a reset the COM port appears TWICE.

  1. ~1 s   a stale node from the interface that is going away
  2. ~10 s  the real 900E interface of the new boot

Opening the stale node produced `ClearCommError ... OSError(22) ... 995`
(`ERROR_OPERATION_ABORTED`) - the handle was invalidated underneath the reader -
and the read returned zero bytes. Every "no HELLO" recorded tonight is
consistent with having opened that ghost rather than the live port.

So a plain "open the moment it appears" race cannot work. This tool:

  * requires the port to be present CONTINUOUSLY for --settle ms before opening,
    which skips the ghost;
  * if the handle dies mid-read, goes back to watching instead of giving up;
  * does the HELLO -> MEMORY_DEBUG -> DDR_DATA read in the SAME session, because
    the HELLO is emitted once per boot and is consumed by the first reader.

Read-only: MEMORY_DEBUG handshake and MEMORY_READ_64 requests only.

Usage
    python auto_grab.py --port COM10 --minutes 6
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
    try:
        return any(p.device.upper() == port.upper()
                   for p in serial.tools.list_ports.comports())
    except Exception:  # noqa: BLE001
        return False


def wait_stable(port: str, settle: float, deadline: float) -> bool:
    """True once the port has been continuously present for `settle` seconds.

    This is what distinguishes the live interface from the ghost: the ghost is
    listed briefly and then removed, so it never survives the settle window.
    """
    streak_start = None
    while time.time() < deadline:
        if present(port):
            if streak_start is None:
                streak_start = time.time()
            elif time.time() - streak_start >= settle:
                return True
        else:
            if streak_start is not None:
                log(f"  port disappeared after {(time.time() - streak_start) * 1000:.0f} ms "
                    f"(ghost node) - continuing to watch")
            streak_start = None
        time.sleep(0.01)
    return False


def try_session(port: str) -> bool:
    """Open and run one full read. Returns True if the DDR_DATA read happened."""
    link = None
    deadline = time.time() + 4.0
    while time.time() < deadline and link is None:
        try:
            link = SerialLink(port, 115200)
        except Exception:  # noqa: BLE001
            if not present(port):
                log("  port gone while opening")
                return False
            time.sleep(0.005)
    if link is None:
        log("  could not open")
        return False
    log("  port open")

    try:
        pkt = link.read_packet(8.0)
        if pkt is None:
            log(f"  no HELLO in 8 s (port alive={not link.dead})")
            return False
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO_REQ, got {cmd:#x}")
            return False
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} ***")
        if mode != MODE_MEMORY_DEBUG:
            log(f"  mode {mode} is not crashdump")
            return False

        link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = link.read_packet(8.0)
        if rsp is None:
            log("  no MEMORY_DEBUG answer")
            return False
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
            log(f"  unexpected {rcmd:#x}")
            return False
        if rcmd == CMD_MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
        else:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
        log(f"  table @{tbl_addr:#x} len={tbl_len}")

        raw = mem_read(link, tbl_addr, tbl_len, tmo=12.0)
        log(f"  table bytes {len(raw)}")
        if not raw:
            return False
        (OUT / "memory_table_raw.bin").write_bytes(raw)
        tables = parse_table(raw)
        print_table(tables)

        ok = False
        for key in ("DDR_DATA", "SHRM_MEM"):
            for e in [t for t in tables
                      if key in (t["file"] or "").upper()
                      or key in (t["desc"] or "").upper()]:
                name = e["file"] or e["desc"]
                log("")
                log(f"  reading {name} {e['len']} B @ {e['addr']:#x}")
                blob = mem_read(link, e["addr"], e["len"], tmo=25.0)
                if blob:
                    fn = OUT / f"{e['addr']:#014x}_{name.replace('/', '_')}"
                    fn.write_bytes(blob)
                    nz = sum(1 for b in blob if b)
                    log(f"    {len(blob)}/{e['len']} B nonzero "
                        f"{nz / max(1, len(blob)):.1%} -> {fn.name}")
                    if key == "DDR_DATA" and len(blob) >= 20:
                        v = struct.unpack_from("<4I", blob, 4)
                        log(f"    DDR training data version {v[0]}.{v[1]}.{v[2]}")
                        ok = True
                else:
                    log("    no data")
        return ok
    finally:
        # NO SAHARA_RESET HERE. Measured 2026-11-11: every session that ended with
        # 0x07 re-enumerated the interface, and the port disappeared 16 ms later.
        # The "boot loop" of this device in this session was produced by the
        # observer, not by the tablet - the same trap as docs/23. A passive 45 s
        # listen with zero writes kept the port up for the whole window.
        link.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--minutes", type=float, default=6.0)
    ap.add_argument("--settle", type=float, default=1.5,
                    help="ms the port must stay present before opening (s)")
    args = ap.parse_args()

    port = args.port.upper()
    OUT.mkdir(exist_ok=True)
    deadline = time.time() + args.minutes * 60

    log("=" * 72)
    log(f"#  auto_grab - debounced HELLO catcher on {port}")
    log(f"#  settle window {args.settle:.1f}s, budget {args.minutes:.0f} min")
    log("=" * 72)
    log("RESET THE TABLET WHEN READY (hold Power ~15 s, then power on).")
    log("Watching for the port...")

    attempt = 0
    while time.time() < deadline:
        if not wait_stable(port, args.settle, deadline):
            break
        attempt += 1
        log(f"  --- attempt {attempt}: port stable, opening ---")
        if try_session(port):
            log("")
            log("SUCCESS - DDR_DATA captured")
            return 0
        log("  attempt finished without data; back to watching")

    log("")
    log("budget exhausted without a successful read")
    return 1


if __name__ == "__main__":
    sys.exit(main())
