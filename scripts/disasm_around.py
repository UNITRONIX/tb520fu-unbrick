#!/usr/bin/env python3
"""disasm_around.py - read the AArch64 instructions around a reference site.

Purpose
-------
find_prop_consumer.py located exactly one reference to `skip_ddr_init_in_EDL`,
in the XBL core at image+0xd244:

    adrp x1, 0x148ac000
    add  x1, x1, #0x619          -> x1 = address of the property name

x1 is the second argument register, so this is a call taking the property name as
its argument. The question is what it is called on: a device-tree node, an SMEM
key, or something else. That is decided by what is loaded into x0 before the call,
and by which function is called.

There is no disassembler available in this environment (capstone is not installed),
so this decodes the common AArch64 encodings directly. It covers enough to read a
prologue and a call setup honestly, and it labels anything it cannot decode as
`?` rather than guessing.

Read-only, offline.

Usage
    python disasm_around.py --image-offset 0xd244 --window 40
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)
IMG2_OFF, IMG2_LEN = 0x032F70, 908256

SEGS = [
    (0x001000, 0x14825000, 0x086000),
    (0x087000, 0x148AB000, 0x011000),
    (0x098000, 0x148BF000, 0x030000),
    (0x0C8000, 0x148EF000, 0x013000),
]

REGS = [f"x{i}" for i in range(31)] + ["sp"]
REGS32 = [f"w{i}" for i in range(31)] + ["wzr"]


def off_to_va(off: int):
    for p_off, va, filesz in SEGS:
        if p_off <= off < p_off + filesz:
            return va + (off - p_off)
    return None


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def decode(insn: int, pc: int) -> str:
    # NOP
    if insn == 0xD503201F:
        return "nop"
    # RET
    if insn == 0xD65F03C0:
        return "ret"

    # ADRP
    if (insn & 0x9F000000) == 0x90000000:
        immlo = (insn >> 29) & 3
        immhi = (insn >> 5) & 0x7FFFF
        imm = sx((immhi << 2) | immlo, 21) << 12
        rd = insn & 0x1F
        return f"adrp {REGS[rd]}, {(pc & ~0xFFF) + imm:#x}"

    # ADD (immediate), 64-bit
    if (insn & 0xFFC00000) == 0x91000000:
        imm12 = (insn >> 10) & 0xFFF
        sh = (insn >> 22) & 1
        rn = (insn >> 5) & 0x1F
        rd = insn & 0x1F
        val = imm12 << (12 if sh else 0)
        return f"add {REGS[rd]}, {REGS[rn]}, #{val:#x}"

    # MOV (register) alias of ORR Xd, XZR, Xm
    if (insn & 0xFFE0FFE0) == 0xAA0003E0:
        rd = insn & 0x1F
        rm = (insn >> 16) & 0x1F
        return f"mov {REGS[rd]}, {REGS[rm]}"

    # LDR (unsigned offset), 64-bit
    if (insn & 0xFFC00000) == 0xF9400000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        rt = insn & 0x1F
        return f"ldr {REGS[rt]}, [{REGS[rn]}, #{imm12 * 8:#x}]"

    # LDR (unsigned offset), 32-bit
    if (insn & 0xFFC00000) == 0xB9400000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        rt = insn & 0x1F
        return f"ldr {REGS32[rt]}, [{REGS[rn]}, #{imm12 * 4:#x}]"

    # LDRB (unsigned offset)
    if (insn & 0xFFC00000) == 0x39400000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        rt = insn & 0x1F
        return f"ldrb {REGS32[rt]}, [{REGS[rn]}, #{imm12}]"

    # CBZ / CBNZ (32-bit)
    if (insn & 0x7E000000) == 0x34000000:
        op = (insn >> 24) & 1
        imm = sx((insn >> 5) & 0x7FFFF, 19) << 2
        rt = insn & 0x1F
        return f"{'cbnz' if op else 'cbz'} {REGS32[rt]}, {pc + imm:#x}"

    # B (unconditional)
    if (insn & 0xFC000000) == 0x14000000:
        imm = sx(insn & 0x3FFFFFF, 26) << 2
        return f"b {pc + imm:#x}"

    # BL
    if (insn & 0xFC000000) == 0x94000000:
        imm = sx(insn & 0x3FFFFFF, 26) << 2
        return f"bl {pc + imm:#x}"

    # BLR
    if (insn & 0xFFFFFC1F) == 0xD63F0000:
        rn = (insn >> 5) & 0x1F
        return f"blr {REGS[rn]}"

    # CMP (immediate) alias SUBS XZR
    if (insn & 0xFFC00000) == 0xF1000000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        return f"cmp {REGS[rn]}, #{imm12:#x}"

    # STR (unsigned offset) 64/32
    if (insn & 0xFFC00000) == 0xF9000000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        rt = insn & 0x1F
        return f"str {REGS[rt]}, [{REGS[rn]}, #{imm12 * 8:#x}]"
    if (insn & 0xFFC00000) == 0xB9000000:
        imm12 = (insn >> 10) & 0xFFF
        rn = (insn >> 5) & 0x1F
        rt = insn & 0x1F
        return f"str {REGS32[rt]}, [{REGS[rn]}, #{imm12 * 4:#x}]"

    return "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    ap.add_argument("--image-offset", type=lambda x: int(x, 0), default=0xD244)
    ap.add_argument("--window", type=int, default=40,
                    help="instructions before and after")
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG2_OFF:IMG2_OFF + IMG2_LEN]

    start = max(0, args.image_offset - args.window * 4)
    end = min(len(img), args.image_offset + (args.window + 1) * 4)

    print("=" * 78)
    print(f"#  XBL core around image+{args.image_offset:#x}")
    print("=" * 78)

    for off in range(start, end, 4):
        insn = struct.unpack_from("<I", img, off)[0]
        va = off_to_va(off)
        mark = "  <<< reference to skip_ddr_init_in_EDL" if off == args.image_offset else ""
        text = decode(insn, va if va is not None else off)
        va_s = f"{va:#012x}" if va is not None else "  (no seg)  "
        print(f"  {off:#08x}  {va_s}  {insn:08x}  {text}{mark}")

    print("\n" + "=" * 78)
    print("#  HOW TO READ THIS")
    print("=" * 78)
    print("  The property name is loaded into x1 at the marked instruction. In the")
    print("  AArch64 calling convention x0 and x1 are the first two arguments, so")
    print("  look backwards for what goes into x0: that is the object the lookup")
    print("  runs against (a DT node, or a config root). Then look forward for")
    print("  'bl <addr>' - the callee is the getter. A 'cbz/cbnz' right after the")
    print("  call is the branch on the property's value, and its target is the")
    print("  code path that skips DDR init.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
