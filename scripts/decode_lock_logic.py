#!/usr/bin/env python3
"""decode_lock_logic.py - derive the lock condition and its failure behaviour.

Two claims need to be exactly right, because everything else depends on them:

  A. what value of the lock byte means "locked"
  B. what happens when the lock partition cannot be read

Both are decided by specific instructions, so they are derived from the encoding
rather than from intuition.

The predicate (image [3], entry 0x149a369c = image+0xb69c):

    0xb6c0  bl 0x149a896c            some setup call
    0xb6c4  cbz w0, 0xb700           w0 == 0 -> go read the partition
    0xb6c8  ...
    0xb6e0  bl 0x149a4df0            attempt the partition read
    0xb6e4  cbz w0, 0xb700           read OK -> compare
    0xb6e8  bl 0x149a3850
    0xb6ec  "...fail to read lenovo lock partition"
    0xb6fc  b 0xb72c
    0xb72c  mov w0, wzr              <-- returns 0
    0xb700  ...
    0xb744  ldrb w8, [sp, #0x20]     the byte from the partition
    0xb748  cmp  w8, #0x1
    0xb74c  csinc/csel ...
    0xb750  b 0xb730

Deriving 0x1a9f17e0 by field, not by name:

    sf=0 op=0 S=0  11010100  Rm=11111(wzr)  cond=0001(NE)  op2=01  Rn=11111(wzr)  Rd=00000(w0)

    op2=01 with cond NE  ->  CSINC w0, wzr, wzr, NE
    CSINC: if cond holds  -> Rd = Rn           (= 0)
           else           -> Rd = Rn + 1       (= 1)

    so:  lock byte == 1  ->  NE false  ->  w0 = 1
         lock byte != 1  ->  NE true   ->  w0 = 0

And the caller tests `cmp w0, #1 / b.ne allow`, so w0 == 1 means LOCKED.

Read-only, offline.

Usage
    python decode_lock_logic.py
"""
from __future__ import annotations

import struct

from image_dump import MelfImages
from a64 import decode


def fields(insn: int) -> str:
    """Break a CSINC/CSEL-family instruction into its fields."""
    sf = (insn >> 31) & 1
    op = (insn >> 30) & 1
    s = (insn >> 29) & 1
    rm = (insn >> 16) & 0x1F
    cond = (insn >> 12) & 0xF
    op2 = (insn >> 10) & 3
    rn = (insn >> 5) & 0x1F
    rd = insn & 0x1F
    R = "x" if sf else "w"
    conds = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
             "hi", "ls", "ge", "lt", "gt", "le", "al", "nv"]
    fam = {0b00: "csel", 0b01: "csinc", 0b10: "csinv", 0b11: "csneg"}
    kind = fam.get(op2, "?")
    if kind == "csel" and rn == 31 and sf == 1 and op == 0:
        kind = "csel"
    return (f"sf={sf} op={op} S={s} {kind} {R}{rd}, "
            f"{R}{rn}, {R}{rm}, {conds[cond]}")


def main() -> int:
    mi = MelfImages()
    img = mi.image(3)

    print("=" * 78)
    print("#  deriving the lock condition")
    print("=" * 78)

    print("\n#  the conditional select at image+0xb74c")
    insn = struct.unpack_from("<I", img, 0xB74C)[0]
    print(f"  raw: {insn:08x}")
    print(f"  decoded fields: {fields(insn)}")
    print()
    print("  CSINC w0, wzr, wzr, NE:")
    print("    cond NE holds  -> w0 = wzr     = 0")
    print("    cond NE fails  -> w0 = wzr + 1 = 1")

    print("\n#  the comparison feeding it")
    insn_cmp = struct.unpack_from("<I", img, 0xB748)[0]
    print(f"  raw: {insn_cmp:08x}   {decode(insn_cmp, 0x149a3748)}")
    print("  cmp w8, #1 sets NE when w8 != 1")

    print("\n#  truth table")
    print("  lock byte | NE after cmp | w0 | caller (cmp w0,#1; b.ne allow)")
    print("  ----------+--------------+----+--------------------------------")
    print("     0      |   true       |  0 | w0 != 1 -> WRITE ALLOWED")
    print("     1      |   false      |  1 | w0 == 1 -> LOCKED")
    print("     2..255 |   true       |  0 | w0 != 1 -> WRITE ALLOWED")
    print()
    print("  => the lock byte must be EXACTLY 1 to lock the device.")

    print("\n#  the failure path")
    print("  image+0xb6e4  cbz w0 -> 0xb700     read succeeded -> compare")
    print("  image+0xb6fc  b 0xb72c             read failed")
    print("  image+0xb72c  mov w0, wzr          return 0")
    print()
    print("  Returning 0 means w0 != 1 at the caller, i.e. WRITE ALLOWED.")
    print()
    print("  => if the lenovo lock partition cannot be read, the programmer")
    print("     treats the device as UNLOCKED. The failure is fail-open.")

    print("\n#  what the read function is")
    print("  The error string names it: 'read_lock_partition: fail to read")
    print("  lenovo lock partition'. So the state comes from a partition on")
    print("  storage, not from a hardware fuse.")

    print("\n" + "=" * 78)
    print("#  SUMMARY")
    print("=" * 78)
    print("  1. Lock state is DATA on UFS, in a partition the code calls the")
    print("     'lenovo lock partition'.")
    print("  2. A byte in that partition equal to 1 locks the device.")
    print("  3. A failed read is treated as unlocked - fail-open.")
    print()
    print("  Consequence for recovery: the gate is not a fuse and not a")
    print("  cryptographic check. It is a byte, and its absence reads as")
    print("  permission. That is a materially different situation from")
    print("  'the SoC refuses by design'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
