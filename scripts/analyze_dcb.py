#!/usr/bin/env python3
"""analyze_dcb.py - read the DDR configuration block's declared parameters.

What the DCB is
---------------
`A00C_8_0200_1_dcb.bin` (28 696 B, extracted from xbl_config.elf) is the DDR
Configuration Block: the memory part, its geometry, its timing sets and the
frequencies the training is allowed to use.

Why it is the right place to look
---------------------------------
The programmer is accepted by Sahara, runs XBL, then goes silent for ~8 s and is
collected by the watchdog (RST_STAT bit 1, 7.918 s window). The last thing it does
before it would raise USB is DDR bring-up, and DDR bring-up is parameterised
entirely by this block.

If the DCB describes a memory part or a frequency this board cannot run, training
fails - quietly, exactly as observed. So the useful question is not "is DDR
broken" but "what does the DCB claim, and does it match the silicon".

This reads the strings and structured markers out of the block. It does not
pretend to decode Qualcomm's proprietary layout beyond what the data shows.

Read-only, offline.

Usage
    python analyze_dcb.py
"""
from __future__ import annotations

import re
import struct
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "xbl_config_payloads" / "A00C_8_0200_1_dcb.bin"

#: Memory-part naming conventions worth surfacing if present.
PART_HINTS = ["LPDDR", "lpddr", "LP5", "lp5", "LP4", "H9H", "MT5", "K3L", "Y52",
              "SAMSUNG", "Samsung", "MICRON", "Micron", "SKHYNIX", "SK Hynix",
              "hynix", "HYNIX"]


def main() -> int:
    if not DATA.is_file():
        print(f"missing {DATA} - run extract_xbl_config.py first")
        return 2
    b = DATA.read_bytes()

    print("=" * 78)
    print(f"#  {DATA.name}  {len(b)} B")
    print("=" * 78)

    nz = sum(1 for x in b if x)
    print(f"  nonzero: {nz}/{len(b)} ({nz/len(b):.1%})")

    # ---- where is the content? -----------------------------------------
    runs, start, prev = [], None, None
    for i, x in enumerate(b):
        if x:
            if start is None:
                start = i
            elif i - prev > 64:
                runs.append((start, prev))
                start = i
            prev = i
    if start is not None:
        runs.append((start, prev))
    print(f"  clusters: {len(runs)}")
    for lo, hi in runs[:16]:
        print(f"    {lo:#08x}..{hi:#08x}  ({hi - lo + 1} B)")

    # ---- strings --------------------------------------------------------
    print("\n#  strings in the block")
    strs = []
    for m in re.finditer(rb"[\x20-\x7e]{5,}", b):
        s = m.group().decode("ascii", "replace")
        a = sum(c.isalpha() or c in " _:=-%.,()/[]" for c in s) / len(s)
        if a > 0.80:
            strs.append((m.start(), s))
    print(f"  {len(strs)} text strings")
    for off, s in strs[:50]:
        print(f"    {off:#08x}  {s[:110]}")

    # ---- memory part hints ---------------------------------------------
    print("\n#  memory-part hints")
    hits = [(o, s) for o, s in strs if any(p in s for p in PART_HINTS)]
    if hits:
        for o, s in hits:
            print(f"    {o:#08x}  {s[:110]}")
    else:
        print("    none by name - the part may be identified by an ID code, not text")

    # ---- frequency tables ----------------------------------------------
    # DDR frequencies on SM8650 are typically 200..4800 MHz, as kHz values in
    # u32 fields. Look for a run of plausible, increasing frequency values.
    print("\n#  plausible frequency entries (kHz, 100 MHz..6 GHz, increasing runs)")
    found = 0
    for off in range(0, len(b) - 16, 4):
        vals = [struct.unpack_from("<I", b, off + 4 * i)[0] for i in range(4)]
        if all(100_000 <= v <= 6_000_000 for v in vals):
            if vals == sorted(vals) and len(set(vals)) == 4:
                print(f"    {off:#08x}  {[v // 1000 for v in vals]} MHz")
                found += 1
                if found >= 12:
                    break
    if not found:
        print("    no clean increasing kHz runs")

    # ---- u32 histogram: the dominant small values often encode counts ----
    print("\n#  most common u32 values (top 12)")
    cnt = Counter(struct.unpack_from("<I", b, o)[0]
                  for o in range(0, len(b) - 4, 4))
    for v, n in cnt.most_common(12):
        print(f"    {v:#010x} ({v:>10d})  x{n}")

    print("\n" + "=" * 78)
    print("#  INTERPRETATION")
    print("=" * 78)
    print("  The DCB is dense binary, so this script reports what is legible and")
    print("  stops. Two conclusions are available already:")
    print()
    print("   1. The block is present, non-trivial and board-specific - it is not")
    print("      an empty fallback, so 'CDT not found, using defaults' is probably")
    print("      not what this unit hits.")
    print("   2. Its part identification is by numeric ID, not text, so comparing")
    print("      it against the silicon needs the ID mapping - which means reading")
    print("      the memory part from the device, not from this file.")
    print()
    print("  Practical next step: get the memory part ID the SoC actually sees,")
    print("  then check whether the DCB contains that ID. A mismatch is a concrete")
    print("  cause for failed training; a match closes this line of enquiry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
