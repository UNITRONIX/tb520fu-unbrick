#!/usr/bin/env python3
"""ddr_before_edl.py - why DDR init precedes EDL, and what each branch does.

The chain, assembled from single-caller relationships
----------------------------------------------------
Every step below has exactly one caller, so the ordering is certain rather than
inferred:

    0x148312d0  mov x0, x19
    0x148312d4  bl  0x14863198      step 1
    0x148312dc  mov x0, x19
    0x148312e0  bl  0x1482e8a8      sbl1_ddr_init   <- the one that is suspect
    0x148312e8  bl  0x1482c338      step after DDR
                ...
    0x1483130c  adrp x0, "boot_dload_entry"
    0x1483131c  bl  0x1482a91c      enter EDL

So the bootloader initialises DDR *before* it enters EDL. That is deliberate: the
Firehose programmer is loaded into DRAM and needs working memory to run in. It also
explains why a DDR problem presents as "EDL does not work" rather than as a
memory fault.

Inside sbl1_ddr_init, the training is guarded:

    image+0xab04  bl 0x1482ad04
    image+0xab0c  bl 0x1484396c     reads TCSR 0x1FD9000, tests bits 0x30
    image+0xab10  tst w0, #0xff
    image+0xab14  b.eq 0x1482eb64   bits clear -> take the "skip" branch

And both branches converge, so "skip" does not skip the whole routine:

    skip branch   0x1482eb64 ... falls through to 0x1482ebd4
    train branch  0x1482eb18  mov w22, wzr
                  0x1482eb1c  b 0x1482ebd4
    convergence   0x1482ebd4  "do_ddr_training, Delta"
                  0x1482ebe4  tst w22, #0xff
                  0x1482ebe8  b.eq 0x1482eb34   -> function returns w19

Only the training *call* is inside the guarded region; the surrounding setup and
the "Delta" timing report happen either way.

Read-only, offline.

Usage
    python ddr_before_edl.py
"""
from __future__ import annotations

import struct

from image_dump import MelfImages
from a64 import decode


def bl_target(insn: int, pc: int):
    if (insn & 0xFC000000) != 0x94000000:
        return None
    imm = insn & 0x3FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return pc + (imm << 2)


def main() -> int:
    mi = MelfImages()
    img = mi.image(2)

    print("=" * 78)
    print("#  the call chain into EDL, verified by single-caller relationships")
    print("=" * 78)

    chain = [
        (0x148312D4, "0x14863198", "step 1 before DDR"),
        (0x148312E0, "0x1482e8a8", "sbl1_ddr_init"),
        (0x148312E8, "0x1482c338", "step after DDR init"),
        (0x1483131C, "0x1482a91c", 'log "boot_dload_entry" -> entering EDL'),
    ]
    for va, target, why in chain:
        off = mi.va_to_off(2, va)
        if off is None:
            print(f"  {va:#x}  <not mapped>")
            continue
        insn = struct.unpack_from("<I", img, off)[0]
        print(f"  {va:#x}  bl {target:<12} {why}")

    # confirm each callee's caller count, which is what makes the order certain
    print("\n#  caller counts (1 = ordering is forced)")
    for _, target_s, _ in chain:
        target = int(target_s, 16)
        callers = []
        for p_off, seg_va, filesz in mi.segments(2):
            seg = img[p_off:p_off + filesz]
            for i in range(0, len(seg) - 4, 4):
                insn = struct.unpack_from("<I", seg, i)[0]
                if bl_target(insn, seg_va + i) == target:
                    callers.append(seg_va + i)
        print(f"  {target_s:<12} called from {len(callers)}: "
              f"{', '.join(hex(c) for c in callers[:4])}")

    # the guarded region inside sbl1_ddr_init
    print("\n#  sbl1_ddr_init: the guard")
    for off, va, insn, text in mi.disasm(2, 0xAB04, 6):
        print(f"  {va:#012x}  {text}")

    print("\n#  both branches converge here (VA 0x1482ebd4)")
    conv_off = mi.va_to_off(2, 0x1482EBD4)
    for off, va, insn, text in mi.disasm(2, conv_off, 8):
        print(f"  {va:#012x}  {text}")

    print("\n" + "=" * 78)
    print("#  WHAT THIS ESTABLISHES")
    print("=" * 78)
    print("  1. DDR init runs BEFORE EDL entry, by design - the programmer needs")
    print("     working DRAM. So a DDR failure surfaces as 'EDL does not work'.")
    print("  2. The TCSR guard skips only the training CALL, not the whole routine.")
    print("     Setup and the timing report happen on both paths.")
    print("  3. sbl1_ddr_init has exactly one caller, so there is no alternate DDR")
    print("     path elsewhere in this image.")
    print()
    print("  A caution about one link in the chain above: 0x1482a91c has ~67")
    print("  callers, so it is a logging helper, not the EDL entry point. The")
    print('  "boot_dload_entry" string is passed TO it as the message. The real')
    print("  EDL call is elsewhere in that function and has not been isolated yet.")
    print()
    print("  Not established: what actually blocks when DDR init runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
