#!/usr/bin/env python3
"""find_func_start.py - locate the real entry of a function containing an address.

Hitting an address mid-function produces nonsense disassembly that looks like data
(it did: a run of strh/tbz pairs that are actually a different function's tail).
Recovering the entry is therefore part of reading code correctly.

Strategy: walk backwards from the address looking for a stack-adjusting prologue
(sub sp, sp, #N) preceded by a terminal instruction (ret / b / nop-padding), which
is where the compiler starts a function.

Read-only, offline.

Usage
    python find_func_start.py --image 3 --offset 0x369c
    python find_func_start.py --image 3 --offset 0x369c --window 0x2000
"""
from __future__ import annotations

import argparse
import struct

from image_dump import MelfImages
from a64 import decode


def is_terminal(insn: int) -> bool:
    return insn in (0xD65F03C0, 0xD503201F) or \
        (insn & 0xFC000000) == 0x14000000  # ret, nop, b


def is_prologue(insn: int) -> bool:
    # sub sp, sp, #imm   (0xD10... with rd=31, rn=31)
    if (insn & 0xFFC00000) == 0xD1000000:
        rd = insn & 0x1F
        rn = (insn >> 5) & 0x1F
        return rd == 31 and rn == 31
    # stp x29, x30, [sp, #-imm]!  (pre-index, rt=29, rt2=30, rn=31)
    if (insn & 0x7FC00000) == 0x29800000:
        rt = insn & 0x1F
        rt2 = (insn >> 10) & 0x1F
        rn = (insn >> 5) & 0x1F
        return rt == 29 and rt2 == 30 and rn == 31
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=None)
    ap.add_argument("--image", type=int, default=3)
    ap.add_argument("--offset", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--window", type=lambda x: int(x, 0), default=0x1000)
    args = ap.parse_args()

    mi = MelfImages(args.melf) if args.melf else MelfImages()
    img = mi.image(args.image)

    print("=" * 78)
    print(f"#  function entry for image [{args.image}] offset {args.offset:#x}")
    print("=" * 78)

    limit = max(0, args.offset - args.window)
    candidates = []
    off = args.offset & ~3
    while off >= limit:
        insn = struct.unpack_from("<I", img, off)[0]
        if is_prologue(insn):
            # a real entry is preceded by a terminal instruction or a gap of NOPs
            prev = struct.unpack_from("<I", img, off - 4)[0] if off >= 4 else 0
            if is_terminal(prev):
                candidates.append(off)
                va = mi.off_to_va(args.image, off)
                print(f"  entry candidate: image+{off:#08x}  va={va}  "
                      f"(preceded by {decode(prev, 0)})")
        off -= 4

    if not candidates:
        print("  no entry found in window; widen with --window")
        return 1

    # the nearest candidate at or before the target is the likely entry
    entry = max(c for c in candidates if c <= args.offset)
    va = mi.off_to_va(args.image, entry)
    print(f"\n  likely entry: image+{entry:#08x}  va={va:#x}")
    print("\n  prologue:")
    for i in range(10):
        o = entry + i * 4
        insn = struct.unpack_from("<I", img, o)[0]
        v = mi.off_to_va(args.image, o)
        print(f"    {o:#08x}  {insn:08x}  {decode(insn, v or 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
