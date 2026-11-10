#!/usr/bin/env python3
"""decode_trn_events.py - did any training stage actually EMIT an event?

Stage 3, and the decisive one.

The stage table in SHRM_MEM looks like this (measured):

    'PLL Precal'               then u32 0x00217de2   + 4 zero bytes
    'DRAM DCC'                 then u32 0x002178ac
    'RCW CDC/Full Cycle Sweep' then u32 0x0020d416
    'DIT - Periodic Training'  then u32 0x0021818a
    'tWCK2DQI (DIT)'           then u32 0x00218b90
    ...

Those u32 values sit at a constant distance after each name and are unique per
stage. The high byte 0x00 with a 24-bit body is the shape of a *message id* in a
Qualcomm debug/trace format, not a pointer (they are below 0x24020000, so they
are not addresses in this mapping) and not a checksum (a checksum would not be
positionally regular).

If those ids are log message ids, then a stage that RAN will have emitted its id
somewhere in the trace buffer, and a stage that never ran will not appear.

So the test is: count occurrences of every stage id across the whole 256 KiB
block. Occurrences inside the table itself are the definition, so they are
excluded by position. Anything else is an emission.

This is the closest we can get, from the host, to "how far did DDR training get".

Offline only.

Usage
    python decode_trn_events.py
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
    if not DATA.is_file():
        print(f"missing {DATA}")
        return 2
    b = DATA.read_bytes()

    print("=" * 78)
    print("#  stage ids and their emissions")
    print("=" * 78)

    # ---- 1. recover id per stage ----------------------------------------
    # Measured layout: a stage record is 0x28 bytes, name first, then the id as a
    # u32 aligned to 4 bytes immediately after the name's terminator (plus zeros).
    # Real ids cluster in 0x00200000..0x002FFFFF - that is what makes them
    # distinguishable from small integers, which is exactly the false positive a
    # naive "first u32 below 0x01000000" search produced (0x21).
    ID_LO, ID_HI = 0x00200000, 0x002FFFFF

    stages = []
    for name in STAGES:
        o = b.find(name)
        if o < 0:
            continue
        name_end = b.find(b"\x00", o)
        align = (name_end + 3) & ~3
        id_off = id_val = None
        for cand in range(align, min(align + 48, len(b) - 4), 4):
            if cand % 4:
                continue
            v = u32(b, cand)
            if ID_LO <= v <= ID_HI:
                id_off, id_val = cand, v
                break
        if id_val is None:
            print(f"  {name.decode():<28} no id in {ID_LO:#x}..{ID_HI:#x} near {o:#x}")
            continue
        stages.append((name.decode(), o, id_off, id_val))

    print(f"\n{'stage':<28} {'name@':>9} {'id@':>9} {'id':>10}")
    print("-" * 62)
    for nm, o, io, iv in stages:
        print(f"{nm:<28} {o:#09x} {io:#09x} {iv:#010x}")

    # ---- 2. count emissions ---------------------------------------------
    print("\n" + "=" * 78)
    print("#  occurrences of each id across the whole block")
    print("=" * 78)
    print(f"\n{'stage':<28} {'id':>10} {'total':>6} {'table':>6} {'elsewhere':>9}")
    print("-" * 66)
    rows = []
    for nm, o, io, iv in stages:
        pat = struct.pack("<I", iv)
        sites = []
        start = 0
        while True:
            k = b.find(pat, start)
            if k < 0:
                break
            if k % 4 == 0:
                sites.append(k)
            start = k + 1
        in_table = [s for s in sites if io - 8 <= s <= io + 8]
        elsewhere = [s for s in sites if s not in in_table]
        rows.append((nm, iv, len(sites), len(in_table), elsewhere))
        print(f"{nm:<28} {iv:#010x} {len(sites):>6} {len(in_table):>6} "
              f"{len(elsewhere):>9}")

    # ---- 3. where are the extra occurrences? ----------------------------
    print("\n" + "=" * 78)
    print("#  emission sites (outside the definition table)")
    print("=" * 78)
    any_found = False
    for nm, iv, tot, tab, elsewhere in rows:
        if not elsewhere:
            continue
        any_found = True
        print(f"\n  {nm}  ({iv:#010x})  {len(elsewhere)} site(s):")
        for s in elsewhere[:10]:
            # show the 32 bytes after the id - a trace record usually carries args
            ctx = b[s:s + 32]
            print(f"    {s:#07x}  {ctx.hex(' ')}")

    # ---- 4. verdict ------------------------------------------------------
    print("\n" + "=" * 78)
    print("#  VERDICT")
    print("=" * 78)
    if any_found:
        emitted = [nm for nm, iv, t, tab, e in rows if e]
        print(f"  Stage ids emitted outside the table: {len(emitted)}")
        for nm in emitted:
            print(f"    - {nm}")
        print("\n  These stages produced trace output, so they executed.")
    else:
        print("  No stage id appears anywhere except its own definition slot.")
        print()
        print("  Two readings, and this data cannot separate them:")
        print("   (a) the trace output goes to a buffer that is not in this block")
        print("       (the pointers next to TRN_PRINT/TRN_ISSUE point to")
        print("        0x24070000 / 0x24072000 / 0x24075000, which are OUTSIDE the")
        print("        256 KiB window we dumped), or")
        print("   (b) the ids are not message ids at all.")
        print()
        print("  Reading (a) is the likely one, and it is actionable: read those")
        print("  addresses directly instead of the SHRM window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
