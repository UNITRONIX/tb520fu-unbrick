#!/usr/bin/env python3
"""control_read.py - always include a known-good address in the same session.

The mistake this prevents
------------------------
read_trn_targets.py read four addresses and got zero bytes from all of them,
including 0x2405f000, which is inside SHRM_MEM - a range that had already been
read successfully. Four failures including one that must work is not evidence
about the four addresses; it is evidence that the session was dead.

A measurement is only interpretable next to a control taken at the same time. So
this reads, in one session, in this order:

    0x24020000    known good (SHRM_MEM base, read successfully before)
    0x2405f000    known good (inside SHRM_MEM)
    0x24070000    the pointer target under test
    0x24072000    the pointer target under test
    0x24075000    the pointer target under test
    0x24020000    known good again (detects mid-session degradation)

If the controls succeed and the targets fail, the targets are genuinely not
exposed. If the controls fail too, the session is bad and nothing can be
concluded.

Read-only.

Usage
    python control_read.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import Link, handshake_memory_debug, mem_read, open_device  # noqa: E402

T0 = time.time()
OUT = Path(__file__).resolve().parent / "control_read"

SEQUENCE = [
    (0x24020000, 0x1000, "control_head"),
    (0x2405F000, 0x1000, "control_tail"),
    (0x24070000, 0x1000, "target_70000"),
    (0x24072000, 0x1000, "target_72000"),
    (0x24075000, 0x1000, "target_75000"),
    (0x24020000, 0x1000, "control_again"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def verdict(blob: bytes) -> str:
    if not blob:
        return "NO ANSWER"
    if all(x == 0xFF for x in blob[:128]):
        return "0xFF"
    if all(x == 0x00 for x in blob[:128]):
        return "zeros"
    nz = sum(1 for x in blob if x)
    return f"DATA (nonzero {nz/len(blob):.0%})"


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
    OUT.mkdir(exist_ok=True)
    log("=" * 70)
    log("#  control_read - known-good and under-test, same session")
    log("=" * 70)

    link, tables = wait_session(200.0)
    if not tables:
        log(">>> no usable session; zombie 9008 needs a power cycle")
        return 1
    log("  session up")

    rows = []
    for addr, length, label in SEQUENCE:
        blob = mem_read(link, addr, length, tmo=6.0)
        v = verdict(blob)
        log(f"  {label:<16} {addr:#010x}  {len(blob):>5d} B  {v}")
        if blob:
            (OUT / f"{label}_{addr:#x}.bin").write_bytes(blob)
        rows.append((label, addr, len(blob), v))

    ctl = [r for r in rows if r[0].startswith("control")]
    tgt = [r for r in rows if r[0].startswith("target")]

    log("")
    log("=" * 70)
    log("#  RESULT")
    log("=" * 70)
    ctl_ok = [r for r in ctl if r[2] > 0]
    tgt_ok = [r for r in tgt if r[2] > 0]
    log(f"  controls answered : {len(ctl_ok)}/{len(ctl)}")
    log(f"  targets  answered : {len(tgt_ok)}/{len(tgt)}")
    log("")
    if len(ctl_ok) < len(ctl):
        log("  => SESSION INVALID: a known-good address failed, so nothing can be")
        log("     concluded about the targets. Re-run on a fresh cycle.")
    elif not tgt_ok:
        log("  => MEANINGFUL NEGATIVE: known-good addresses read fine while all")
        log("     three pointer targets returned nothing. Those addresses are not")
        log("     exposed by the crash handler, so the trace buffer cannot be read")
        log("     this way - even though the pointers to it exist in SHRM_MEM.")
    else:
        log("  => targets answered; inspect the saved files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
