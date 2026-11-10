#!/usr/bin/env python3
"""ddr_map_probe.py - how much DDR will the 900E crashdump actually give us?

Motivation
----------
docs/07-dead-ends.md states: "DDR does not answer in crashdump - confirmed with
small blocks." That conclusion rests on ONE probe at 0x9fa00000 that returned
0xFF. crash_region_probe.py has since shown that DDRCS0_0 at 0x80000000 DOES
answer, with real AArch64 content. So the old conclusion is too broad and was
never actually tested across the range.

Why it matters
--------------
The Firehose programmer is accepted by Sahara, then never speaks. Two
explanations survived in the notes:

  (a) it dies during DDR training / hardware init,
  (b) its own battery guard (DBC) powers the device down instead of starting.

A partially mapped or partially trained DDR turns (a) from a hypothesis into a
measurement - and if DDR is genuinely incomplete, the fault is on the board and
no host-side action can help. If DDR answers cleanly across its whole populated
range, (a) loses its footing and the search moves back to power/DBC.

Method (read-only, no writes, no mode switch, no upload)
-------------------------------------------------------
  1. one MEMORY_DEBUG session
  2. read the small diagnostics: RST_STAT, PMIC_PON, PMON_HIS, SMEMINFO
  3. coarse sample of DDRCS0 every --step bytes, classify each
  4. refine the good->bad boundary at 1 MiB granularity
  5. probe the high CS base addresses reported by the device's own table

Usage
    python ddr_map_probe.py
    python ddr_map_probe.py --step 67108864 --time 180
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

from crash_region_probe import (  # noqa: E402
    Link,
    handshake_memory_debug,
    mem_read,
    open_device,
    parse_table,
)

OUT = Path(__file__).resolve().parent / "ddr_map_probe"
T0 = time.time()

# Diagnostics worth reading in the same session, by filename in the device table.
DIAG = ["RST_STAT.BIN", "PMIC_PON.BIN", "PMON_HIS.BIN", "SMEMINFO.BIN",
        "FSM_STS.BIN", "DBG_EN.BIN", "sbl_pmic_dump.bin"]

# DDR chip-select bases as advertised by the device's own memory table.
CS_BASES = [
    (0x80000000, "DDRCS0_0"),
    (0x880000000, "DDRCS1_0"),
    (0x900000000, "DDRCS1_1"),
    (0x980000000, "DDRCS1_2"),
    (0xA00000000, "DDRCS2_0"),
    (0xA80000000, "DDRCS2_1"),
    (0xB00000000, "DDRCS2_2"),
    (0xB80000000, "DDRCS2_3"),
]

#: DDRCS0 window. The device reports 2 GiB for CS0_0, starting at 0x80000000
#: (this matches load.cmm: `d.load.binary DDRCS0_0.BIN 0x80000000`).
CS0_BASE = 0x80000000
CS0_SIZE = 0x80000000

PON_REASONS = {
    0: "PON_KPDPWR (power key)", 1: "PON_RESIN (Vol-)", 2: "PON_KPDPWR_RESIN",
    3: "PON_CBLPWR (charger insert)", 4: "PON_RTC", 5: "PON_DC_CHG",
    6: "PON_USB_CHG", 7: "PON_PON1", 8: "PON_PON2", 9: "PON_PON3",
    10: "PON_HARD_RESET", 11: "PON_SMPL",
}


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def kind(blob: bytes) -> str:
    """Coarse classification, tuned to answer one question: is this real memory?"""
    if not blob:
        return "no-answer"
    head = blob[:256]
    if len(head) >= 4 and head[:4] == b"\x7fELF":
        return "ELF"
    if all(b == 0xFF for b in head):
        return "0xFF"
    if all(b == 0x00 for b in head):
        return "zeros"
    nz = sum(1 for b in blob if b)
    words = struct.unpack_from(f"<{min(len(blob), 2048)//4}I", blob, 0)
    plausible = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
    ratio = plausible / max(1, len(words))
    return f"real(code {ratio:.0%}, nz {nz/len(blob):.0%})"


def readable(blob: bytes) -> bool:
    k = kind(blob)
    return k.startswith(("real", "ELF"))


def wait_session(budget: float):
    """Catch a usable crashdump node and return (dev, link, tables)."""
    deadline = time.time() + budget
    while time.time() < deadline:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception as err:  # noqa: BLE001
            log(f"  handshake exception {type(err).__name__}: {err}")
            link = tables = None
        if tables:
            return dev, link, tables
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        end = time.time() + 60
        while time.time() < end and usb.core.find(idVendor=0x05C6, idProduct=0x900E):
            time.sleep(0.05)
    return None, None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=32 << 20, help="coarse scan stride")
    ap.add_argument("--time", type=float, default=150.0, help="wait budget for a session")
    ap.add_argument("--budget", type=float, default=8.0, help="max seconds spent scanning")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 72)
    log("#  ddr_map_probe - how far does DDR answer from the crashdump?")
    log("=" * 72)

    dev, link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable 900E session (device busy, not in crashdump, or wedged)")
        return 1

    names = {e["file"]: e for e in tables}

    # ---- 1. diagnostics ---------------------------------------------------
    log("")
    log("-" * 72)
    log("#  reset / power diagnostics")
    log("-" * 72)
    diag = {}
    for want in DIAG:
        e = names.get(want)
        if not e:
            log(f"  {want:<20s} not in table")
            continue
        blob = mem_read(link, e["addr"], min(e["len"], 4096), tmo=2.0)
        diag[want] = blob
        if blob:
            (OUT / f"diag_{want}").write_bytes(blob)
        log(f"  {want:<20s} {len(blob):>5d} B  {blob[:32].hex(' ')}")

    if len(diag.get("RST_STAT.BIN", b"")) >= 4:
        v = struct.unpack_from("<I", diag["RST_STAT.BIN"], 0)[0]
        bits = [f"b{i}" for i in range(32) if v & (1 << i)]
        log("")
        log(f"  RST_STAT = 0x{v:08x}  bits: {', '.join(bits) or 'none'}")
        if v & 0x2:
            log("    b1 set -> WATCHDOG reset (the CPU stopped responding)")
    if len(diag.get("PMIC_PON.BIN", b"")) >= 8:
        v = struct.unpack_from("<Q", diag["PMIC_PON.BIN"], 0)[0]
        log(f"  PMIC_PON = 0x{v:016x}  reason={PON_REASONS.get(v & 0xF, 'unknown')}")

    # ---- 2. high chip selects --------------------------------------------
    log("")
    log("-" * 72)
    log("#  DDR chip-select bases (addresses taken from the device's own table)")
    log("-" * 72)
    ddr_entries = [e for e in tables if e["file"].upper().startswith("DDRCS")]
    cs0 = None
    for e in ddr_entries:
        blob = mem_read(link, e["addr"], 4096, tmo=5.0)
        log(f"  {e['addr']:#012x}  {e['file']:<12s} len={e['len']:<12d} {kind(blob)} ({len(blob)} B)")
        if e["file"].upper().startswith("DDRCS0_"):
            cs0 = e
    if cs0 is None:
        log("  !! no DDRCS0 entry in the table - cannot scan")
        return 1

    # ---- 3. coarse scan of CS0 -------------------------------------------
    base = cs0["addr"]
    limit = cs0["addr"] + cs0["len"]
    log("")
    log("-" * 72)
    log(f"#  {cs0['file']} coarse scan, stride {args.step // (1 << 20)} MiB, "
        f"window {base:#x}..{limit:#x}")
    log("-" * 72)
    base, limit = CS0_BASE, CS0_BASE + CS0_SIZE
    scan_start = time.time()
    samples = []
    addr = base
    truncated = False
    while addr < limit:
        if time.time() - scan_start > args.budget:
            truncated = True
            log(f"  ... scan budget reached at {addr - base:#x} into CS0")
            break
        blob = mem_read(link, addr, 4096, tmo=5.0)
        samples.append((addr, kind(blob)))
        addr += args.step

    good = [a for a, k in samples if k.startswith(("real", "ELF"))]
    bad = [a for a, k in samples if not k.startswith(("real", "ELF"))]
    log(f"  samples: {len(samples)}   readable: {len(good)}   not: {len(bad)}")
    if good:
        log(f"  lowest readable : {min(good):#x}")
        log(f"  highest readable: {max(good):#x}")
    for a, k in samples:
        log(f"    {a:#012x}  {k}")

    # ---- 4. refine the boundary ------------------------------------------
    boundary = None
    if good and bad:
        last_good = max(good)
        first_bad_after = min([a for a in bad if a > last_good], default=None)
        if first_bad_after is not None:
            log("")
            log(f"#  refining boundary between {last_good:#x} and {first_bad_after:#x} @1 MiB")
            lo, hi = last_good, first_bad_after
            while hi - lo > (1 << 20):
                if time.time() - scan_start > args.budget + 6:
                    log("  (refinement budget reached)")
                    break
                mid = (lo + hi) // 2
                k = kind(mem_read(link, mid, 4096, tmo=1.2))
                log(f"    {mid:#012x}  {k}")
                if k.startswith(("real", "ELF")):
                    lo = mid
                else:
                    hi = mid
            boundary = lo
            log(f"  readable CS0 ends near {boundary:#x} "
                f"({(boundary - base) / (1 << 30):.2f} GiB into CS0)")

    # ---- summary ---------------------------------------------------------
    log("")
    log("=" * 72)
    log("#  SUMMARY")
    log("=" * 72)
    if boundary is not None:
        log(f"  DDRCS0 readable extent from {base:#x}: "
            f"{(boundary - base) / (1 << 30):.2f} GiB")
        log("  A truncated but non-zero extent means the crash handler exposes only")
        log("  part of DDR, OR DDR is only partly trained. The two look identical")
        log("  from here and must not be conflated.")
    elif good and not bad:
        log(f"  all {len(good)} CS0 samples readable"
            f"{' (scan truncated)' if truncated else ''}")
    else:
        log("  no readable CS0 samples")
    log(f"  artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
