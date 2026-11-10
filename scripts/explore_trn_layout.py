#!/usr/bin/env python3
"""explore_trn_layout.py - find the real training buffers inside SHRM_MEM.

Stage 1 of decoding. The labels 'TRN_PRINT' and 'TRN_ISSUE' sit next to each
other in a string table, so they name buffers rather than describe them. The
descriptors (address + length) must be elsewhere in the block.

Strategy: shared memory is mapped at 0x24020000 for 256 KiB, so a pointer into
it is any 32-bit value in [0x24020000, 0x24060000). Pointers into DDR are in
[0x80000000, 0x88000000). Finding those values, and the words next to them that
look like lengths, is how the buffer layout gets established instead of guessed.

Offline only.

Usage
    python explore_trn_layout.py
"""
from __future__ import annotations

import struct
from collections import defaultdict
from pathlib import Path

SHRM_BASE = 0x24020000
SHRM_SIZE = 0x40000
DATA = Path(__file__).resolve().parent / "pmic_state_probe" / "SHRM_MEM.BIN"


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def main() -> int:
    if not DATA.is_file():
        print(f"missing {DATA}")
        return 2
    b = DATA.read_bytes()
    print("=" * 78)
    print(f"#  {DATA.name}  {len(b)} B   mapped at {SHRM_BASE:#x}..{SHRM_BASE + SHRM_SIZE:#x}")
    print("=" * 78)

    # ---- 1. pointers into shared memory ----------------------------------
    shr_ptrs = defaultdict(list)
    for off in range(0, len(b) - 3, 4):
        v = u32(b, off)
        if SHRM_BASE <= v < SHRM_BASE + SHRM_SIZE:
            shr_ptrs[v].append(off)
    print(f"\n# values pointing INTO shared memory: {sum(len(v) for v in shr_ptrs.values())} "
          f"({len(shr_ptrs)} distinct targets)")
    for target in sorted(shr_ptrs)[:40]:
        sites = shr_ptrs[target]
        rel = target - SHRM_BASE
        print(f"  -> {target:#010x} (file {rel:#07x})  from {len(sites)} site(s): "
              f"{', '.join(hex(s) for s in sites[:4])}")

    # ---- 2. pointers into DDR -------------------------------------------
    ddr_ptrs = defaultdict(list)
    for off in range(0, len(b) - 3, 4):
        v = u32(b, off)
        if 0x80000000 <= v < 0x88000000:
            ddr_ptrs[v].append(off)
    print(f"\n# values pointing into DDR CS0: "
          f"{sum(len(v) for v in ddr_ptrs.values())} ({len(ddr_ptrs)} distinct)")
    for target in sorted(ddr_ptrs)[:20]:
        print(f"  -> {target:#010x}  from {len(ddr_ptrs[target])} site(s)")

    # ---- 3. context around the label table -------------------------------
    tp = b.find(b"TRN_PRINT")
    ti = b.find(b"TRN_ISSUE")
    print(f"\n# label table context (TRN_PRINT @ {tp:#x}, TRN_ISSUE @ {ti:#x})")
    lo = (tp - 64) & ~3
    for off in range(lo, lo + 256, 16):
        words = " ".join(f"{u32(b, off + i):08x}" for i in range(0, 16, 4))
        text = b[off:off + 16]
        printable = "".join(chr(c) if 32 <= c < 127 else "." for c in text)
        print(f"  {off:#07x}  {words}  |{printable}|")

    # ---- 4. look for (ptr, len) descriptor pairs ------------------------
    print("\n# candidate (ptr, len) descriptor pairs in shared memory")
    found = 0
    for off in range(0, len(b) - 7, 4):
        a = u32(b, off)
        n = u32(b, off + 4)
        if SHRM_BASE <= a < SHRM_BASE + SHRM_SIZE and 16 <= n <= SHRM_SIZE:
            rel = a - SHRM_BASE
            if rel + n <= SHRM_SIZE:
                print(f"  {off:#07x}: ptr={a:#010x} (file {rel:#06x}) len={n:#x} ({n})")
                found += 1
                if found > 25:
                    print("  ...")
                    break
    if not found:
        print("  none - buffers are probably referenced by offset, not absolute pointer")

    # ---- 5. offset-style descriptors (u32 offset, u32 len) --------------
    print("\n# candidate (offset, len) pairs, offset relative to SHRM base")
    found = 0
    for off in range(0, len(b) - 7, 4):
        o = u32(b, off)
        n = u32(b, off + 4)
        if 0 < o < SHRM_SIZE and 64 <= n <= SHRM_SIZE and o + n <= SHRM_SIZE:
            # require the pair to sit in a plausible table area (upper half)
            if off > 0x10000:
                print(f"  {off:#07x}: off={o:#07x} len={n:#x} ({n}) -> "
                      f"ends {o + n:#07x}")
                found += 1
                if found > 25:
                    print("  ...")
                    break
    if not found:
        print("  none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
