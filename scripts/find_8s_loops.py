#!/usr/bin/env python3
"""find_8s_loops.py - what in the programmer could take ~8 seconds?

The remaining clue
------------------
The device leaves the bus 8.016 s after DONE. The watchdog window is 7.918 s, so
roughly 98 ms of work happens before the stall. Gates that refuse have been ruled
out (write gate is a byte; battery loop is bounded at 0.4-65 s and does not fit).

So the question is: is there a loop in the programmer whose period lands near
8 s? If one exists and involves storage or DDR, it is a strong candidate for the
hang.

Method
------
Scan every image for `bl` sites that target a delay routine, then look at the
argument passed in the immediately preceding instructions. When the argument is a
constant, the delay is known; when it is a register, note where it was loaded.

Delay routines already identified in this image:
    0x14832ac8   thin wrapper -> 0x14847cd4  (microseconds)

This deliberately reports near-misses too. A loop of 7.9 s or 8.2 s is as
interesting as one of exactly 8.0 s, because the 98 ms of work sits on top.

Read-only, offline.

Usage
    python find_8s_loops.py
    python find_8s_loops.py --min 4 --max 20
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_dump import MelfImages  # noqa: E402

DELAY_FNS = {0x14832AC8, 0x14847CD4}


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=4.0, help="min seconds of interest")
    ap.add_argument("--max", type=float, default=20.0, help="max seconds of interest")
    args = ap.parse_args()

    mi = MelfImages()
    print("=" * 78)
    print(f"#  delay calls whose argument implies {args.min}..{args.max} seconds")
    print("=" * 78)

    for n in (2, 3, 4):
        img = mi.image(n)
        segs = mi.segments(n)
        print(f"\n--- image [{n}]  {len(img)} B")

        found = 0
        for p_off, seg_va, filesz in segs:
            seg = img[p_off:p_off + filesz]
            for i in range(0, len(seg) - 4, 4):
                insn = struct.unpack_from("<I", seg, i)[0]
                if (insn & 0xFC000000) != 0x94000000:
                    continue
                imm = insn & 0x3FFFFFF
                if imm & (1 << 25):
                    imm -= 1 << 26
                pc = seg_va + i
                if pc + (imm << 2) not in DELAY_FNS:
                    continue

                # find how w0 / x0 was loaded in the preceding 4 instructions
                us = None
                for back in range(1, 5):
                    o = i - back * 4
                    if o < 0:
                        break
                    prev = struct.unpack_from("<I", seg, o)[0]
                    # MOVZ w0, #imm [, lsl #n]
                    if (prev & 0x7F800000) == 0x52800000 and (prev & 0x1F) == 0:
                        hw = (prev >> 21) & 3
                        imm16 = (prev >> 5) & 0xFFFF
                        us = imm16 << (16 * hw)
                        break
                    # MOVK w0, #imm, lsl #16 (continuing a MOVZ)
                    if (prev & 0x7F800000) == 0x72800000 and (prev & 0x1F) == 0:
                        hw = (prev >> 21) & 3
                        imm16 = (prev >> 5) & 0xFFFF
                        if us is None:
                            us = 0
                        us |= imm16 << (16 * hw)
                        continue
                if us is None:
                    continue
                secs = us / 1_000_000
                if not (args.min <= secs <= args.max):
                    continue
                found += 1
                # what does the code do around it?
                ctx = []
                for j in (-2, -1, 0, 1, 2):
                    oo = i + j * 4
                    if 0 <= oo < len(seg):
                        val = struct.unpack_from("<I", seg, oo)[0]
                        ctx.append(f"{val:08x}")
                print(f"  {pc:#012x}  delay {us:>10} us = {secs:7.3f} s   "
                      f"ctx[{' '.join(ctx)}]")

        if not found:
            print("  none in this range")

    print("\n" + "=" * 78)
    print("#  HOW TO READ THIS")
    print("=" * 78)
    print("  A single delay of ~8 s would be a suspicious place to wait. But note")
    print("  that the observed 8.016 s is only ~98 ms more than the watchdog window,")
    print("  so a candidate is more likely to be a LOOP whose total lands near 8 s")
    print("  than one long sleep. Constants below show the per-iteration delay; the")
    print("  iteration count is what has to be multiplied in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
