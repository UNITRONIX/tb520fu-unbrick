#!/usr/bin/env python3
"""dbc_trace.py - reconstruct the battery-recovery loop and its bounds.

What was found
--------------
All the DBC (Dynamic Battery Check) strings live in image [2] - the XBL core - and
none in image [3] (Firehose). So the battery gate runs during XBL initialisation,
which is exactly where the programmer goes silent.

The recovery function at 0x14837c7c contains a loop with a one-second delay:

    0x14838008  "battery recover failed"
    0x14838014  movz w0, #0x4240
    0x14838018  movk w0, #0xf, lsl #16     -> 1 000 000
    0x1483801c  bl 0x14832ac8              delay(1 000 000 us) = 1 s
    0x14838020  bl 0x14832bcc              retry

and a threshold comparison against a configured value:

    0x14837f48  ldrh w8, [x21, #0xbc]      configured threshold
    0x14837f50  ldrh w9, [x29, #-0xc]      measured value
    0x14837f58  sub  w22, w8, w9           difference
    0x14837f60  tbnz x22, #31, ...         negative -> different path

plus an inner pacing loop bounded by a loaded count:

    0x14837ef4  ldrh w8, [x21, #0xa4]
    0x14837ef8  cmp  w24, w8
    0x14837efc  b.cs 0x14837f34            exit when w24 >= count
    0x14837f00  bl 0x14837b98
    0x14837f14  mul  w0, w8, w23
    0x14837f18  bl 0x14832ac8              delay(w8 * w23)
    0x14837f28  add  w24, w24, #0x1f4      advance by 500
    0x14837f2c  sub  w27, w27, #0x1f4
    0x14837f30  b 0x14837ef4

This script resolves the delay helper to units, then reports whether the outer
recovery loop is bounded - which is the question that decides whether a battery
condition can hang boot indefinitely.

Read-only, offline.

Usage
    python dbc_trace.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_dump import MelfImages  # noqa: E402

IMG = 2
RECOVERY = 0x14837C7C
INNER_LOOP = 0x14837EF4
RETRY_DELAY = 0x14838014


def bl_target(img: bytes, mi, va: int):
    off = mi.va_to_off(IMG, va)
    if off is None:
        return None
    insn = struct.unpack_from("<I", img, off)[0]
    if (insn & 0xFC000000) != 0x94000000:
        return None
    imm = insn & 0x3FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return va + (imm << 2)


def main() -> int:
    mi = MelfImages()
    img = mi.image(IMG)

    print("=" * 78)
    print("#  DBC: is the recovery loop bounded?")
    print("=" * 78)

    # ---- what does the delay helper actually implement? ----------------
    print("\n#  delay helper used by the retry")
    off = mi.va_to_off(IMG, 0x14832AC8)
    print(f"  0x14832ac8 @ image+{off:#x}")
    for o, va, insn, text in mi.disasm(IMG, off, 6):
        print(f"    {va:#012x}  {text}")

    # follow it if it is a thin wrapper
    tgt = bl_target(img, mi, 0x14832AC8)
    if tgt:
        print(f"  it branches to {tgt:#x}; following")
        o2 = mi.va_to_off(IMG, tgt)
        if o2:
            for o, va, insn, text in mi.disasm(IMG, o2, 16):
                print(f"    {va:#012x}  {text}")

    # ---- the threshold comparison --------------------------------------
    print("\n#  threshold comparison")
    for va, note in ((0x14837F48, "load configured threshold"),
                     (0x14837F4C, "load constant"),
                     (0x14837F50, "load measured value"),
                     (0x14837F58, "difference"),
                     (0x14837F60, "branch on sign")):
        o = mi.va_to_off(IMG, va)
        insn = struct.unpack_from("<I", img, o)[0]
        from a64 import decode
        print(f"    {va:#012x}  {insn:08x}  {decode(insn, va)}   ; {note}")

    # what does 0x14837f48's constant mean? 0x86a0 = 34464
    print("\n#  the constant loaded just before the comparison")
    o = mi.va_to_off(IMG, 0x14837F4C)
    insn = struct.unpack_from("<I", img, o)[0]
    imm16 = (insn >> 5) & 0xFFFF
    print(f"    0x14837f4c movz w21, #{imm16:#x}  ({imm16})")
    o = mi.va_to_off(IMG, 0x14837F54)
    insn = struct.unpack_from("<I", img, o)[0]
    imm16b = (insn >> 5) & 0xFFFF
    val = imm16 | (imm16b << 16)
    print(f"    0x14837f54 movk w21, #{imm16b:#x}, lsl #16  -> {val:#x} ({val})")

    # ---- the inner pacing loop ----------------------------------------
    print("\n#  inner pacing loop (bounded by a loaded count)")
    o = mi.va_to_off(IMG, INNER_LOOP)
    for off2, va, insn, text in mi.disasm(IMG, o, 16):
        print(f"    {va:#012x}  {text}")

    print("\n" + "=" * 78)
    print("#  WHAT THIS ESTABLISHES")
    print("=" * 78)
    print("  - The battery gate is in the XBL core (image 2), not in Firehose.")
    print("    It therefore runs before the XML listener could ever exist.")
    print("  - The retry inserts a ONE SECOND delay between attempts.")
    print("  - An inner loop advances in steps of 0x1f4 (500) and is bounded by a")
    print("    count read from a configuration structure, so at least that loop")
    print("    terminates.")
    print()
    print("  Still open: whether the OUTER retry loop has a bound. The disassembly")
    print("  above shows the delay and the retry call, but the loop's exit condition")
    print("  has not been isolated - which matters, because an unbounded retry with a")
    print("  one-second delay is indistinguishable from a hang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
