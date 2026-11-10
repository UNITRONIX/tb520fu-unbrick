#!/usr/bin/env python3
"""ddr_near_probe.py - is DDR readable past its first 4 KiB, or not?

Why this is not already answered
--------------------------------
ddr_map_probe.py sampled DDRCS0 at 128 MiB stride and found only the very first
sample readable. A 128 MiB stride cannot distinguish:

  * "only the first page is exposed"          (mapping limit)
  * "the first 64 KiB / 1 MiB / 16 MiB is fine, then it stops"  (partial mapping)
  * "specific low windows are exposed"        (crash handler design)

Those are different findings with different consequences, so this probes the
first megabyte at fine granularity and prints the exact boundary instead of
leaving it to inference.

Also re-tests the ABL load address 0x9fa00000 that ddr_peek.py reported as 0xFF
in an earlier session - with the current device state, and with a longer timeout
than that script used.

Read-only. One MEMORY_DEBUG session.

Usage
    python ddr_near_probe.py
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

from crash_region_probe import Link, handshake_memory_debug, mem_read, open_device  # noqa: E402

T0 = time.time()


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def kind(blob: bytes) -> str:
    if not blob:
        return "no-answer"
    head = blob[:256]
    if all(b == 0xFF for b in head):
        return "0xFF"
    if all(b == 0x00 for b in head):
        return "zeros"
    nz = sum(1 for b in blob if b)
    words = struct.unpack_from(f"<{min(len(blob), 1024)//4}I", blob, 0)
    ok = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
    return f"real(code {ok/max(1,len(words)):.0%}, nz {nz/len(blob):.0%})"


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
        while time.time() < end2 and usb.core.find(idVendor=0x05C6, idProduct=0x900E):
            time.sleep(0.05)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=160.0)
    args = ap.parse_args()

    log("=" * 72)
    log("#  ddr_near_probe - where exactly does readable DDR stop?")
    log("=" * 72)

    link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable session")
        return 1

    base = 0x80000000
    print_hdr = True
    last_good = None
    first_bad = None
    for off in (0x0, 0x1000, 0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000,
                0x80000, 0x100000, 0x200000, 0x400000, 0x800000, 0x1000000,
                0x2000000, 0x4000000, 0x8000000, 0x10000000):
        if print_hdr:
            log("")
            log(f"{'offset':>10}  {'address':>12}  verdict")
            log("-" * 52)
            print_hdr = False
        blob = mem_read(link, base + off, 4096, tmo=6.0)
        verdict = kind(blob)
        log(f"{off:#10x}  {base + off:#12x}  {verdict}")
        if verdict.startswith("real"):
            last_good = off
        elif first_bad is None:
            first_bad = off

    # the ABL load address the earlier session called unmapped
    log("")
    log("#  ABL load address re-test (ddr_peek.py reported 0xFF here)")
    for addr in (0x9FA00000, 0x9FA02000, 0x80000000):
        blob = mem_read(link, addr, 4096, tmo=6.0)
        log(f"  {addr:#012x}  {kind(blob)}")

    log("")
    log("=" * 72)
    log("#  RESULT")
    log("=" * 72)
    log(f"  last readable offset from CS0 base : "
        f"{hex(last_good) if last_good is not None else 'none'}")
    log(f"  first unreadable offset            : "
        f"{hex(first_bad) if first_bad is not None else 'none'}")
    if last_good is not None and first_bad is not None and first_bad > last_good:
        log(f"  => DDR is exposed for the first {first_bad:#x} bytes, then not.")
        log("     That is a mapping/extent fact, NOT evidence about training.")
    elif last_good is not None:
        log("  => every probe in the first 256 MiB answered.")
    else:
        log("  => nothing answered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
