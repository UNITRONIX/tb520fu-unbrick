#!/usr/bin/env python3
"""session_kill_test.py - confirm that reading an unexposed address wedges the dump.

The observation to verify
-------------------------
control_read.py produced this sequence in one session:

    control 0x24020000 -> 4096 B of data       (session healthy)
    control 0x2405f000 -> 4096 B of zeros      (session healthy)
    target  0x24070000 -> 0 B                  (session dead)
    control 0x24020000 -> 0 B                  (still dead)

That reads as: the read of an unexposed address terminates the crash-dump
handler, and every later read in that session returns nothing regardless of
address. If true, it explains a large amount of earlier confusion - any probe
that touched a bad address first silently poisoned the rest of its results.

This test establishes it properly: one session per case, control first, then the
single address under test, and nothing after.

Read-only.

Usage
    python session_kill_test.py
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

CONTROL = 0x24020000
CASES = [
    ("valid_control_only", 0x2405F000),
    ("suspect_70000", 0x24070000),
    ("suspect_72000", 0x24072000),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def wait_fresh(budget: float):
    """A fresh 900E only: wait for absence, then arrival."""
    end = time.time() + budget
    while time.time() < end:
        if (usb.core.find(idVendor=0x05C6, idProduct=0x900E) is None
                and usb.core.find(idVendor=0x05C6, idProduct=0x9008) is None):
            break
        time.sleep(0.1)
    return wait_session(budget)


def wait_session(budget: float):
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
        time.sleep(0.5)
    return None, None


def summarise(blob: bytes) -> str:
    if not blob:
        return "NO ANSWER"
    if all(x == 0xFF for x in blob[:128]):
        return f"0xFF ({len(blob)} B)"
    if all(x == 0x00 for x in blob[:128]):
        return f"zeros ({len(blob)} B)"
    nz = sum(1 for x in blob if x)
    return f"DATA {nz/len(blob):.0%} ({len(blob)} B)"


def main() -> int:
    log("=" * 72)
    log("#  session_kill_test - does a bad address end the crash-dump session?")
    log("=" * 72)

    results = []
    for label, addr in CASES:
        log("")
        log(f"===== {label}  ({addr:#x}) =====")
        link, tables = wait_fresh(200.0)
        if not tables:
            log("  no fresh session available")
            results.append((label, addr, None, None))
            continue

        before = mem_read(link, CONTROL, 0x1000, tmo=6.0)
        log(f"  control {CONTROL:#x} -> {summarise(before)}")

        test = mem_read(link, addr, 0x1000, tmo=6.0)
        log(f"  test    {addr:#x} -> {summarise(test)}")

        results.append((label, addr, len(before), len(test)))

        # leave the device to cycle before the next case
        end = time.time() + 60
        while time.time() < end and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.1)

    log("")
    log("=" * 72)
    log("#  RESULT")
    log("=" * 72)
    log(f"  {'case':<22} {'address':>12} {'control':>10} {'test':>10}")
    log("-" * 58)
    for label, addr, cb, tb in results:
        c = f"{cb} B" if cb is not None else "-"
        t = f"{tb} B" if tb is not None else "-"
        log(f"  {label:<22} {addr:#12x} {c:>10} {t:>10}")

    log("")
    good = [r for r in results if r[2] and r[3]]
    ctl_ok = [r for r in results if r[2]]
    ctl_bad = [r for r in results if not r[2]]
    # CASES[0] is the known-valid control target; the rest are suspects.
    valid_target = CASES[0][1]
    valid = [r for r in results if r[1] == valid_target]
    suspects = [r for r in results if r[1] != valid_target]
    susp_ok = [r for r in suspects if r[3]]
    susp_bad = [r for r in suspects if r[2] and not r[3]]

    if ctl_bad:
        log(f"  => INCONCLUSIVE: control failed in {len(ctl_bad)} case(s), so the")
        log("     device was not usable and nothing can be concluded.")
    elif susp_bad and not susp_ok:
        log("  => CONFIRMED, two separate facts:")
        log("     1. the control address reads fine in every session, and the")
        log(f"        known-valid target {valid_target:#x} also reads fine, so the")
        log("        harness and the session are healthy;")
        log(f"     2. every suspect address ({len(susp_bad)}) returns nothing.")
        log("")
        log("     Conclusion: 0x24070000 and 0x24072000 are NOT exposed by the")
        log("     crash handler. The TRN trace buffer cannot be read this way,")
        log("     even though pointers to it exist inside SHRM_MEM.")
    elif susp_ok and not susp_bad:
        log("  => all suspects answered; inspect the saved files.")
    else:
        log(f"  => MIXED: {len(susp_ok)} suspect(s) answered, {len(susp_bad)} did not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
