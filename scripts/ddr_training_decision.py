#!/usr/bin/env python3
"""ddr_training_decision.py - what decides whether DDR training runs in EDL?

The question
------------
The programmer is accepted by PBL (`END 0x00`, `DONE` acknowledged), then goes
silent for ~8 s, then the watchdog collects it (RST_STAT bit 1, 7.918 s window).
The last thing it should do before raising USB is bring DDR up.

So: is training actually attempted, or is it skipped by a condition?

Answer, from the code
---------------------
Inside `sbl1_ddr_init` (va 0x1482e8a8) the `do_ddr_training, Start` message is
guarded by a call to va 0x1484396c:

    image+0xab04  bl 0x1482ad04
    image+0xab0c  bl 0x1484396c
    image+0xab10  tst w0, #0xff
    image+0xab14  b.eq 0x1482eb64        w0 == 0 -> skip training

and 0x1484396c is the tail of the function starting at 0x148438e4:

    0x1484396c  movz w8, #0x9000
    0x14843970  movk w8, #0x1fd, lsl #16     w8 = 0x1FD9000
    0x14843974  ldrh w8, [x8]                read a 16-bit register
    0x14843978  tst  w8, #0x30               test bits 4 and 5
    0x1484397c  1a9f07e0                     csinc w0, wzr, wzr, EQ
    0x14843980  ret

`0x1a9f07e0` decoded by field: sf=0 op=0 S=0 11010100 Rm=wzr cond=0000(EQ) op2=00
Rn=wzr Rd=w0 -> `CSINC w0, wzr, wzr, EQ`.

    CSEL family with op2=00 is CSEL: w0 = Rn when cond holds, else Rm.
    Here Rn = Rm = wzr, so this is a conditional zero: w0 = 0 either way,
    and the meaningful part is the flag outcome, not the value.

Careful: with Rn == Rm == wzr the select is degenerate, so the branch on the
result is what matters. The caller tests with `tst w0, #0xff / b.eq`, i.e. it
skips training when the returned value is zero.

The register
------------
Address 0x1FD9000 is a TCSR block. The neighbouring strings in the same function
region name the subsystem:

    "TCSR reg value 0x%x "
    "boot_ddr.c"
    "boot_platforminfo.c"
    "Enter PBL EDL USB"
    "Enter PBL EDL PCIe"

So the decision is made from a hardware status register in the TCSR region,
consulted from boot_ddr.c, in the EDL path.

Read-only, offline.

Usage
    python ddr_training_decision.py
"""
from __future__ import annotations

from image_dump import MelfImages
from a64 import decode


def main() -> int:
    mi = MelfImages()
    print("=" * 78)
    print("#  the DDR training decision in the devprg XBL")
    print("=" * 78)

    print("\n#  sbl1_ddr_init: the guard around 'do_ddr_training, Start'")
    for off, va, insn, text in mi.disasm(2, 0xAB04, 8):
        mark = ""
        if insn == 0x34000280:
            mark = "   <- skip training when w0 == 0"
        print(f"  {va:#012x}  {insn:08x}  {text}{mark}")

    print("\n#  the predicate that produces that value (func 0x148438e4 tail)")
    for off, va, insn, text in mi.disasm(2, 0x1F96C, 8):
        print(f"  {va:#012x}  {insn:08x}  {text}")

    print("\n#  the caller's test, in full")
    for off, va, insn, text in mi.disasm(2, 0xAB0C, 6):
        print(f"  {va:#012x}  {insn:08x}  {text}")

    print("\n" + "=" * 78)
    print("#  WHAT IS ESTABLISHED")
    print("=" * 78)
    print("  1. The decision uses a 16-bit register read at physical 0x1FD9000.")
    print("  2. It tests bits 0x30 of that value.")
    print("  3. The result gates the 'do_ddr_training' message and the training")
    print("     call that follows it.")
    print("  4. The register lives in a TCSR block, and the surrounding strings")
    print("     place this code in boot_ddr.c on the EDL path.")
    print()
    print("#  WHAT IS NOT ESTABLISHED")
    print("=" * 78)
    print("  - The semantics of bits 0x30 on this SoC. TCSR layouts are")
    print("    per-platform and not published; the meaning cannot be inferred")
    print("    from the bit numbers alone.")
    print("  - Whether the value differs between a cold boot and an EDL entry.")
    print("  - Whether training is what actually hangs. This shows when it is")
    print("    SKIPPED, not what happens when it runs.")
    print()
    print("  The honest next step is to read 0x1FD9000 from the crash dump, if")
    print("  that register is exposed, and compare it against what the code")
    print("  expects. That converts the remaining unknown into a number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
