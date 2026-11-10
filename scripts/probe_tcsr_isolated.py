#!/usr/bin/env python3
"""probe_tcsr_isolated.py - one address per session, control on both sides.

The failure that forced this design
-----------------------------------
probe_tcsr.py read four TCSR addresses in one session and got nothing for all of
them - and the control read taken AFTERWARD also failed. That makes the result
uninterpretable: an unexposed address and a killed session look identical.

The crash handler appears to terminate when asked for an address it does not
expose. So each address must be tested in its own session, with a control read
both before and after, and the session discarded if either control fails.

Read-only.

Usage
    python probe_tcsr_isolated.py
    python probe_tcsr_isolated.py --time 400
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
CONTROL = 0x24020000

CASES = [
    (0x81B75038, 4, "RST_STAT (known good)"),
    (0x1FD9000, 0x10, "TCSR 0x1FD9000 (the DDR guard)"),
    (0x1FD9004, 0x10, "TCSR 0x1FD9004"),
    (0x1FD0000, 0x10, "TCSR block base"),
    (0x10080000, 0x10, "DCC_SRAM (appears in device table)"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def desc(blob: bytes) -> str:
    if not blob:
        return "NO ANSWER"
    if all(x == 0xFF for x in blob[:32]):
        return "0xFF (not exposed)"
    if all(x == 0x00 for x in blob[:32]):
        return "zeros"
    u32 = struct.unpack_from("<I", blob, 0)[0]
    u16 = struct.unpack_from("<H", blob, 0)[0]
    return f"u16={u16:#06x} u32={u32:#010x} ({len(blob)} B)"


def wait_absent(budget: float = 90.0) -> bool:
    end = time.time() + budget
    while time.time() < end:
        if (usb.core.find(idVendor=0x05C6, idProduct=0x900E) is None
                and usb.core.find(idVendor=0x05C6, idProduct=0x9008) is None):
            return True
        time.sleep(0.05)
    return False


def get_session(budget: float = 150.0):
    end = time.time() + budget
    while time.time() < end:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception:  # noqa: BLE001
            link = tables = None
        if tables:
            return link, tables
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=400.0)
    args = ap.parse_args()

    log("=" * 74)
    log("#  probe_tcsr_isolated - one case per session, control on both sides")
    log("=" * 74)

    verdicts = []
    for addr, n, what in CASES:
        log("")
        log(f"===== {what}  ({addr:#x}) =====")

        # a fresh cycle before every case: the previous case may have killed it
        if not wait_absent(90):
            log("  device did not cycle; waiting for a session anyway")

        link, tables = get_session(args.time / len(CASES) + 60)
        if not tables:
            log("  no session available - skipping")
            verdicts.append((what, addr, None, None, None))
            continue

        pre = mem_read(link, CONTROL, 0x40, tmo=5.0)
        log(f"  control before : {desc(pre)}")

        test = mem_read(link, addr, n, tmo=5.0)
        log(f"  test           : {desc(test)}")

        post = mem_read(link, CONTROL, 0x40, tmo=5.0)
        log(f"  control after  : {desc(post)}")

        verdicts.append((what, addr, pre, test, post))

        # let the device cycle so the next case starts clean
        end = time.time() + 70
        while time.time() < end and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.1)

    log("")
    log("=" * 74)
    log("#  RESULT")
    log("=" * 74)
    log(f"  {'case':<30} {'pre':>6} {'test':>6} {'post':>6}  verdict")
    log("  " + "-" * 68)
    for what, addr, pre, test, post in verdicts:
        p = "ok" if pre else "-"
        t = "ok" if test else "NO"
        q = "ok" if post else "-"
        if pre is None:
            v = "no session"
        elif not pre:
            v = "control failed - inconclusive"
        elif test:
            v = "EXPOSED"
        elif post:
            v = "not exposed (session survived)"
        else:
            v = "killed the session"
        log(f"  {what:<30} {p:>6} {t:>6} {q:>6}  {v}")

    exposed = [v for v in verdicts if v[3]]
    log("")
    if exposed:
        log("  Readable targets:")
        for what, addr, pre, test, post in exposed:
            log(f"    {addr:#010x}  {what}")
            u16 = struct.unpack_from("<H", test, 0)[0]
            log(f"      u16 = {u16:#06x}   (bits 0x30 = {u16 & 0x30:#04x})")
    else:
        log("  No target answered. If the controls passed for those cases, the TCSR")
        log("  block is genuinely not reachable from the crash dump.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
