#!/usr/bin/env python3
"""read_trn_targets.py - read the trace buffers the pointers actually name.

Why these addresses
-------------------
explore_trn_layout.py found three u32 values sitting immediately after the
'TRN_ISSUE' label in SHRM_MEM:

    0x24070000   0x24072000   0x24075000

SHRM_MEM.BIN was dumped from 0x24020000 for 256 KiB, i.e. up to 0x24060000. All
three targets are ABOVE that window, which is consistent with decode_trn_events.py
finding zero stage-id emissions inside the dump: the emission log is not in the
block we pulled.

So this reads them directly, with SAHARA_MEMORY_READ, one window at a time.
Nothing here depends on the previous dump being complete.

Read-only.

Usage
    python read_trn_targets.py
    python read_trn_targets.py --addr 0x24070000 --len 0x1000
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

OUT = Path(__file__).resolve().parent / "trn_targets"
T0 = time.time()

#: Targets recovered from the SHRM_MEM label area.
TARGETS = [
    (0x24070000, 0x2000, "ptr_a"),
    (0x24072000, 0x2000, "ptr_b"),
    (0x24075000, 0x2000, "ptr_c"),
    # also re-read the end of the known block, to see whether it continues
    (0x2405F000, 0x1000, "shrm_tail"),
]

#: Stage ids, to check whether any of them appear in these windows.
STAGE_IDS = {
    "PLL Precal": 0x00217DE2,
    "DRAM DCC": 0x002178AC,
    "RCW CDC/Full Cycle Sweep": 0x0021818A,
    "DIT - Periodic Training": 0x00218B90,
    "tWCK2DQI (DIT)": 0x00218B96,
    "CLKIO DCC Monitor": 0x00217024,
    "RDT4 DCC Monitor": 0x0021744E,
    "IO_Qual Vref Training": 0x00212226,
    "Low Freq DQ CDC perbit": 0x00219ACE,
}


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def classify(blob: bytes) -> str:
    if not blob:
        return "no-answer"
    head = blob[:256]
    if all(x == 0xFF for x in head):
        return "0xFF (not mapped / not dumpable)"
    if all(x == 0x00 for x in head):
        return "all zeros"
    nz = sum(1 for x in blob if x)
    return f"data (nonzero {nz/len(blob):.0%})"


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
    ap.add_argument("--addr", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--len", type=lambda x: int(x, 0), default=0x2000)
    ap.add_argument("--time", type=float, default=170.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 74)
    log("#  read_trn_targets - follow the pointers out of the dumped window")
    log("=" * 74)

    link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable crashdump session (zombie 9008 needs a power cycle)")
        return 1
    log(f"  session up, {len(tables)} regions")

    targets = [(args.addr, args.len, "custom")] if args.addr else TARGETS

    results = {}
    for addr, length, label in targets:
        log("")
        log(f"  {label}: {length:#x} B @ {addr:#x}")
        blob = mem_read(link, addr, length, tmo=10.0)
        log(f"    got {len(blob)} B  {classify(blob)}")
        if not blob:
            continue
        fn = OUT / f"{addr:#012x}_{length:x}_{label}.bin"
        fn.write_bytes(blob)
        results[addr] = blob

        hits = []
        for name, sid in STAGE_IDS.items():
            pat = struct.pack("<I", sid)
            pos = blob.find(pat)
            if pos >= 0:
                hits.append((name, pos))
        if hits:
            log(f"    STAGE IDS FOUND ({len(hits)}):")
            for name, pos in hits:
                log(f"      {name} @ +{pos:#x}")
                log(f"        ctx: {blob[pos:pos+32].hex(' ')}")
        else:
            log("    no stage ids in this window")

        # printable strings, which a print buffer would be full of
        import re
        strs = [m.group().decode("ascii", "replace")
                for m in re.finditer(rb"[\x20-\x7e]{8,}", blob)]
        clean = [s for s in strs
                 if sum(c.isalpha() or c in " _:=-%.,()/" for c in s) / len(s) > 0.85]
        if clean:
            log(f"    {len(clean)} text-like strings:")
            for s in clean[:12]:
                log(f"      | {s[:100]}")

    log("")
    log("=" * 74)
    log("#  RESULT")
    log("=" * 74)
    if not results:
        log("  none of the targets answered.")
        log("  That means either the pointers are not buffer addresses, or the")
        log("  crash handler does not expose that range. Both are conclusions;")
        log("  do not treat this as a tool failure without checking a known-good")
        log("  address (e.g. 0x24020000) in the same session.")
    else:
        found = sum(1 for blob in results.values()
                    if any(struct.pack("<I", s) in blob for s in STAGE_IDS.values()))
        log(f"  windows read: {len(results)}")
        log(f"  windows containing stage ids: {found}")
    log(f"  artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
