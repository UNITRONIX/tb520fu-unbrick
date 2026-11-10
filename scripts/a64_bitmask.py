#!/usr/bin/env python3
"""a64_bitmask.py - decode AArch64 logical-immediate bitmasks.

Logical immediates (AND/ORR/EOR/ANDS with #imm, and MOV #imm aliases) encode their
value in N:immr:imms. Printing them as raw fields makes comparisons unreadable, and
XBL uses them constantly for flag tests, so decode them properly.

Algorithm per the ARM ARM "DecodeBitMasks".
"""

from __future__ import annotations


def _replicate(pattern: int, esize: int, width: int) -> int:
    out = 0
    count = width // esize
    for i in range(count):
        out |= pattern << (i * esize)
    return out


def decode_bitmask(n: int, immr: int, imms: int, width: int) -> int:
    """Return the immediate value for a logical-immediate instruction.

    Raises ValueError when the encoding is reserved (all ones immediate).
    """
    len_ = 0
    # find the highest set bit in N:~imms
    combined = ((n << 6) | ((~imms) & 0x3F))
    for bit in range(6, -1, -1):
        if combined & (1 << bit):
            len_ = bit
            break
    if len_ < 1:
        # 32-bit variants use len 0
        esize = 32
    else:
        esize = 1 << len_

    if width < esize:
        raise ValueError("esize larger than register width")

    levels = esize - 1
    s = imms & levels
    r = immr & levels
    if s == levels:
        raise ValueError("reserved: all-ones immediate")

    welem = (1 << (s + 1)) - 1
    # rotate right by r within esize
    r %= esize
    welem = ((welem >> r) | (welem << (esize - r))) & ((1 << esize) - 1)
    return _replicate(welem, esize, width)
