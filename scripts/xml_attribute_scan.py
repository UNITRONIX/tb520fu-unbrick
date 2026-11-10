#!/usr/bin/env python3
"""xml_attribute_scan.py - which XML attributes does this Firehose accept?

Why it matters
--------------
The write gate turned out to be a byte in `lenovolock` (LUN 0, sectors 774-901),
and the read path is NOT gated. So the moment the XML listener comes up, reading
that partition becomes possible - which tells us the actual lock state.

But reading it requires addressing a specific LUN and sector range. Firehose does
that through XML attributes, and which ones this build supports decides whether we
can target LUN 0 explicitly or whether we are dependent on a GPT read.

This scans the programmer's string table for the attribute names it knows.

Read-only, offline.

Usage
    python xml_attribute_scan.py
"""
from __future__ import annotations

import re
from pathlib import Path

from image_dump import MelfImages

#: Attribute names Firehose implementations commonly recognise.
CANDIDATES = [
    "physical_partition_number",
    "start_sector",
    "num_partition_sectors",
    "SECTOR_SIZE_IN_BYTES",
    "num_sectors",
    "size_in_KB",
    "filename",
    "label",
    "partition",
    "slot",
    "sparse",
    "readbackverify",
    "verify",
    "wipe",
    "skip",
    "pages_per_block",
    "byte_offset",
]

#: Verbs, for context.
VERBS = ["configure", "read", "program", "erase", "patch", "power", "nop",
         "getstorageinfo", "peek", "poke", "setbootablestorage",
         "getsha256digest", "getgptinfo"]


def main() -> int:
    mi = MelfImages()
    img = mi.image(3)
    base = 0x110B50

    print("=" * 78)
    print("#  Firehose XML surface")
    print("=" * 78)

    print("\n#  attributes")
    print(f"  {'name':<30} {'count':>6}  first occurrence")
    print("  " + "-" * 62)
    for name in CANDIDATES:
        pat = name.encode()
        n = img.count(pat)
        first = img.find(pat)
        where = f"image+{first:#08x}" if first >= 0 else "-"
        print(f"  {name:<30} {n:>6}  {where}")

    print("\n#  verbs")
    for v in VERBS:
        pat = v.encode()
        n = img.count(pat)
        if n:
            print(f"  {v:<26} x{n}")

    # ---- look for GPT / LUN handling strings ---------------------------
    print("\n#  strings about LUN / partition selection")
    seen = set()
    for m in re.finditer(rb"[\x20-\x7e]{10,}", img):
        s = m.group().decode("ascii", "replace")
        low = s.lower()
        if not any(k in low for k in ("lun", "partition number", "physical partition",
                                      "start sector", "sector size", "gpt")):
            continue
        if s in seen:
            continue
        a = sum(c.isalpha() or c in " _:=-%.,()/[]" for c in s) / len(s)
        if a < 0.72:
            continue
        seen.add(s)
        print(f"  {base + m.start():#08x}  {s[:104]}")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  If physical_partition_number and start_sector are present, a read of")
    print("  lenovolock can be requested directly by LUN and sector, with no")
    print("  dependency on how the GPT is parsed.")
    print()
    print("  That is the first concrete action to take once the programmer speaks:")
    print()
    print("      LUN 0, start_sector 774, num_partition_sectors 128")
    print()
    print("  and inspect the first byte. 1 means locked, anything else means the")
    print("  write path would be permitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
