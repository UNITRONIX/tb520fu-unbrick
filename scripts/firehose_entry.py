#!/usr/bin/env python3
"""firehose_entry.py - where does the programmer start, and what is first?

Everything so far established that the programmer is accepted, runs briefly (~98 ms
of work before the watchdog window expires), and never raises its XML listener. The
question that has not been asked is the simplest one: **what does its entry point
do first?**

If the first thing it touches is storage or a security call, and that call blocks,
then everything downstream is moot - and the fix has to be aimed at that call rather
than at the XML layer.

This disassembles from the image's own ELF entry point and annotates string
references, so the opening sequence can be read in order.

Read-only, offline.

Usage
    python firehose_entry.py
    python firehose_entry.py --count 80
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a64 import decode  # noqa: E402
from image_dump import MelfImages  # noqa: E402

IMG = 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=70)
    args = ap.parse_args()

    mi = MelfImages()
    img = mi.image(IMG)

    e_entry = struct.unpack_from("<Q", img, 24)[0]
    e_phoff = struct.unpack_from("<Q", img, 32)[0]
    e_phnum = struct.unpack_from("<H", img, 56)[0]

    print("=" * 78)
    print(f"#  image [{IMG}] entry and segments")
    print("=" * 78)
    print(f"  ELF entry: {e_entry:#x}")
    for i in range(e_phnum):
        o = e_phoff + i * 56
        p_type = struct.unpack_from("<I", img, o)[0]
        p_off, p_va, p_pa, p_fsz, p_msz = struct.unpack_from("<QQQQQ", img, o + 8)
        if p_fsz:
            print(f"  ph[{i}] type={p_type:#x} off={p_off:#x} "
                  f"vaddr={p_va:#010x} filesz={p_fsz:#x}")

    entry_off = mi.va_to_off(IMG, e_entry)
    if entry_off is None:
        print(f"\n  entry {e_entry:#x} is not inside a mapped segment")
        return 1

    print(f"\n  entry maps to image+{entry_off:#x}")
    print("\n" + "=" * 78)
    print(f"#  first {args.count} instructions from the entry point")
    print("=" * 78)

    rows = list(mi.disasm(IMG, entry_off, args.count))

    # resolve adrp+add pairs so string loads are visible inline
    resolved = {}
    for idx, (off, va, insn, text) in enumerate(rows):
        if not text.startswith("adrp"):
            continue
        try:
            page = int(text.split(", ")[1], 16)
        except Exception:  # noqa: BLE001
            continue
        rd = text.split(",")[0].split()[1]
        for j in range(idx + 1, min(idx + 6, len(rows))):
            t2 = rows[j][3]
            if not t2.startswith("add "):
                continue
            parts = t2[4:].split(", ")
            if len(parts) == 3 and parts[0] == rd and parts[1] == rd:
                try:
                    resolved[rows[idx][0]] = page + int(parts[2].lstrip("#"), 16)
                except Exception:  # noqa: BLE001
                    pass
            break

    for off, va, insn, text in rows:
        note = ""
        if off in resolved:
            s = mi.cstr(IMG, resolved[off])
            if s:
                note = f'   ; {resolved[off]:#x} "{s[:52]}"'
        va_s = f"{va:#010x}" if va else f"{off:#08x}"
        print(f"  {va_s}  {insn:08x}  {text}{note}")

    print("\n" + "=" * 78)
    print("#  HOW TO READ THIS")
    print("=" * 78)
    print("  The first call chain tells you what the programmer needs before it can")
    print("  talk. Storage open, security initialisation, and USB bring-up are the")
    print("  usual four. Whichever appears first and does not return is the hang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
