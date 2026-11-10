#!/usr/bin/env python3
"""stage_status_probe.py - are there per-stage STATUS values next to the names?

Stage 2 of decoding. The upper half of SHRM_MEM holds a table of training stage
names (PLL Precal, DRAM DCC, ...). If each name is the label of a record that
carries a result, the status should sit at a fixed offset from the name.

This script prints, for every stage name, the surrounding words so the record
stride and any status field become visible instead of assumed. It also looks for
a run of small monotonically increasing values, which is what a per-stage
"progress" or "pass index" looks like.

Offline only.

Usage
    python stage_status_probe.py
"""
from __future__ import annotations

import struct
from pathlib import Path

DATA = Path(__file__).resolve().parent / "pmic_state_probe" / "SHRM_MEM.BIN"

STAGES = [
    b"PLL Precal", b"DRAM DCC", b"RCW CDC/Full Cycle Sweep", b"DIT - Periodic Training",
    b"tWCK2DQI (DIT)", b"CLKIO DCC Monitor", b"RDT4 DCC Monitor",
    b"IO_Qual Vref Training", b"Low Freq DQ CDC perbit", b"HighSpeed DIT",
    b"PXI Config",
]


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def main() -> int:
    b = DATA.read_bytes()
    print("=" * 78)
    print("#  per-stage context in SHRM_MEM")
    print("=" * 78)

    offsets = []
    for st in STAGES:
        o = b.find(st)
        offsets.append((st.decode(), o))
        print(f"\n--- {st.decode()}  @ {o:#07x}" if o >= 0 else f"\n--- {st.decode()} ABSENT")

    # Are the names evenly spaced? A constant stride means a table of records.
    present = [o for _, o in offsets if o >= 0]
    print("\n# stride analysis")
    diffs = [present[i + 1] - present[i] for i in range(len(present) - 1)]
    print(f"  name offsets : {[hex(o) for o in present]}")
    print(f"  gaps         : {diffs}")
    if diffs and len(set(diffs)) == 1:
        print(f"  => CONSTANT stride {diffs[0]} - these are records, not loose strings")
    else:
        print("  => gaps vary; the names are printed adjacently, not one record each")

    # Dump the neighbourhood of the first few names as words.
    print("\n# word context around the first four names")
    for name, o in offsets[:4]:
        if o < 0:
            continue
        lo = (o - 32) & ~3
        print(f"\n  {name} @ {o:#x}")
        for off in range(lo, lo + 96, 16):
            words = " ".join(f"{u32(b, off + i):08x}" for i in range(0, 16, 4))
            txt = "".join(chr(c) if 32 <= c < 127 else "." for c in b[off:off + 16])
            mark = " <<<" if off <= o < off + 16 else ""
            print(f"    {off:#07x}  {words}  |{txt}|{mark}")

    # Look for a contiguous run of small increasing u16/u32 values, which is the
    # shape of a per-stage pass/status vector.
    print("\n# candidate status vectors (8+ consecutive values <= 0x10)")
    found = 0
    for off in range(0, len(b) - 32, 4):
        vals = [u32(b, off + 4 * i) for i in range(8)]
        if all(v <= 0x10 for v in vals) and len(set(vals)) > 3:
            print(f"  {off:#07x}  {vals}")
            found += 1
            if found >= 20:
                break
    if not found:
        print("  none")

    # The pointers seen next to the TRN_* labels point above the dumped window.
    print("\n# pointer target check (from explore_trn_layout.py)")
    for p in (0x24070000, 0x24072000, 0x24075000):
        end = 0x24020000 + len(b)
        inside = 0x24020000 <= p < end
        print(f"  {p:#010x}  file offset {p - 0x24020000:#07x}  "
              f"{'inside dump' if inside else 'OUTSIDE dumped window'}")
    print(f"\n  dumped window: 0x24020000..{0x24020000 + len(b):#010x}")
    print("  => if the TRN buffers live at 0x24070000+, this dump cannot contain them.")
    print("     They must be read directly with SAHARA_MEMORY_READ, one window at a time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
