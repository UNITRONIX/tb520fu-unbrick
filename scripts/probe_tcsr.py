#!/usr/bin/env python3
"""probe_tcsr.py - can we read the DDR-decision register from the crash dump?

Why this specific address
-------------------------
The devprg XBL decides whether to train DDR by reading a 16-bit register at
physical 0x1FD9000 and testing bits 0x30:

    0x1484396c  movz w8, #0x9000
    0x14843970  movk w8, #0x1fd, lsl #16
    0x14843974  ldrh w8, [x8]        -> 0x1FD9000
    0x14843978  tst  w8, #0x30
    0x1484397c  1cinc/csel ...
    0x14843980  ret

If the 900E crash-dump handler exposes that address, the value can be read
directly and the remaining unknown becomes a number instead of an inference.

The probe is honest about failure: it always reads a control address from the
same session first, because a dead session and an unmapped address look
identical (that mistake was made earlier in this project - see
docs/15-crashdump-memory-access.md).

Read-only. Single MEMORY_DEBUG session, no uploads, no mode switch beyond it.

Usage
    python probe_tcsr.py
    python probe_tcsr.py --time 180
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import handshake_memory_debug, mem_read, open_device  # noqa: E402

T0 = time.time()

#: Always-read control: inside SHRM_MEM, known to answer on a healthy session.
CONTROL = 0x24020000

#: Addresses under test, with what each would tell us.
TARGETS = [
    (0x1FD9000, 0x10, "TCSR DDR-decision register (the guard)"),
    (0x1FD9004, 0x10, "next word in the same TCSR block"),
    (0x1FD9008, 0x10, "next word"),
    (0x1FD0000, 0x10, "TCSR block base (context)"),
]

#: Registers the crash dump already gives us, for comparison.
KNOWN = [
    (0x81B75038, 4, "RST_STAT (expect 0x3: watchdog)"),
    (0x81B75048, 8, "PMIC_PON"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def classify(blob: bytes) -> str:
    if not blob:
        return "NO ANSWER"
    head = blob[:64]
    if all(x == 0xFF for x in head):
        return "0xFF fill (not exposed)"
    if all(x == 0x00 for x in head):
        return "all zeros"
    nz = sum(1 for x in blob if x)
    u16 = struct.unpack_from("<H", blob, 0)[0]
    u32 = struct.unpack_from("<I", blob, 0)[0]
    return f"DATA u16={u16:#06x} u32={u32:#010x} nonzero={nz}/{len(blob)}"


def wait_session(budget: float):
    end = time.time() + budget
    while time.time() < end:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception as err:  # noqa: BLE001
            log(f"  handshake: {type(err).__name__}")
            link = tables = None
        if tables:
            return link, tables
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        end2 = time.time() + 70
        while time.time() < end2 and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.05)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=170.0)
    args = ap.parse_args()

    log("=" * 72)
    log("#  probe_tcsr - read the register that gates DDR training")
    log("=" * 72)

    link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable crashdump session (zombie 9008 needs a power cycle)")
        return 1
    log(f"  session up, {len(tables)} regions in the device table")

    # ---- control first -------------------------------------------------
    ctl = mem_read(link, CONTROL, 0x100, tmo=6.0)
    log(f"  CONTROL {CONTROL:#x} -> {classify(ctl)}")
    if not ctl:
        log("  !! control failed: session is dead, nothing below is meaningful")
        return 1

    # ---- known registers ----------------------------------------------
    log("")
    log("#  known registers (sanity)")
    for addr, n, what in KNOWN:
        blob = mem_read(link, addr, n, tmo=4.0)
        log(f"  {addr:#010x} {what:<32} {classify(blob)}")

    # ---- targets -------------------------------------------------------
    log("")
    log("#  TCSR targets")
    results = []
    for addr, n, what in TARGETS:
        blob = mem_read(link, addr, n, tmo=4.0)
        verdict = classify(blob)
        log(f"  {addr:#010x} {what:<42} {verdict}")
        results.append((addr, what, blob))

    # ---- control again, to detect mid-session death --------------------
    ctl2 = mem_read(link, CONTROL, 0x100, tmo=6.0)
    log("")
    log(f"  CONTROL again -> {classify(ctl2)}")

    log("")
    log("=" * 72)
    log("#  RESULT")
    log("=" * 72)
    ok = [r for r in results if r[2] and any(x != 0xFF for x in r[2][:64])]
    if not ctl2:
        log("  INCONCLUSIVE: the session died partway through, so a missing")
        log("  answer above cannot be distinguished from an unexposed address.")
    elif ok:
        for addr, what, blob in ok:
            v = struct.unpack_from("<H", blob, 0)[0]
            bits = v & 0x30
            log(f"  {addr:#010x} = {v:#06x}   bits 0x30 = {bits:#04x}")
            log(f"      training in EDL would be "
                f"{'SKIPPED (bits clear)' if bits == 0 else 'ATTEMPTED (bits set)'}")
        log("")
        log("  Note: this is the register value as the crash handler sees it, which")
        log("  may differ from what the programmer read during its own run.")
    else:
        log("  MEANINGFUL NEGATIVE: controls read fine, all TCSR targets failed.")
        log("  The crash handler does not expose the TCSR block, so the guard's")
        log("  input cannot be read from the host in this state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
