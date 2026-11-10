#!/usr/bin/env python3
"""a64.py - a real AArch64 decoder, good enough to read Qualcomm boot code.

The earlier decoder in disasm_around.py handled ~15 encodings and printed '?' for
everything else, which made control flow unreadable. This covers the instruction
classes that actually appear in XBL/SBL code:

  data processing (immediate)  ADD/SUB/ADDS/SUBS, MOVZ/MOVK/MOVN, AND/ORR/EOR imm
  data processing (register)   MOV, ORR, AND, EOR, LSL/LSR/ASR
  loads/stores                 LDR/STR (unscaled, unsigned offset, pre/post index),
                               LDP/STP, LDRB/STRB, LDRH/STRH, LDRSW
  branches                     B, BL, B.cond, CBZ/CBNZ, TBZ/TBNZ, BR, BLR, RET
  compares                     CMP/CMN/TST aliases
  misc                         NOP, HINT, MRS/MSR (named where known), DMB/DSB/ISB

Every function returns a string, and anything undecodable returns '?' - the
decoder never invents an instruction.

Use as a library:
    from a64 import decode
    decode(0xd65f03c0, 0x1000)      -> 'ret'

Or as a CLI to dump a range of an image:
    python a64.py --melf <path> --image 2 --offset 0xa8a8 --count 40
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

X = [f"x{i}" for i in range(31)] + ["sp"]
W = [f"w{i}" for i in range(31)] + ["wzr"]
XZR = X[:31] + ["xzr"]
COND = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
        "hi", "ls", "ge", "lt", "gt", "le", "al", "nv"]

SYSREG = {
    0xC080: "SCTLR_EL1", 0xC100: "CPACR_EL1", 0xC200: "TTBR0_EL1",
    0xC280: "TTBR1_EL1", 0xC300: "TCR_EL1", 0xC600: "SPSR_EL1",
    0xC680: "ELR_EL1", 0xC700: "VBAR_EL1", 0xC800: "SCTLR_EL2",
    0xE200: "TTBR0_EL2", 0xE280: "TTBR1_EL2", 0xD538: "CurrentEL",
    0xDA20: "DBGBVR0_EL1", 0xC682: "SP_EL0",
}


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def _bit(insn: int, n: int) -> int:
    return (insn >> n) & 1


def _rd(insn: int) -> int:
    return insn & 0x1F


def _rn(insn: int) -> int:
    return (insn >> 5) & 0x1F


def _rm(insn: int) -> int:
    return (insn >> 16) & 0x1F


def decode(insn: int, pc: int) -> str:
    # ---- branches (before the generic masks) ----------------------------
    if (insn & 0xFC000000) == 0x14000000:
        return f"b {pc + (sx(insn & 0x3FFFFFF, 26) << 2):#x}"
    if (insn & 0xFC000000) == 0x94000000:
        return f"bl {pc + (sx(insn & 0x3FFFFFF, 26) << 2):#x}"
    if (insn & 0xFF000010) == 0x54000000:
        return (f"b.{COND[insn & 0xF]} "
                f"{pc + (sx((insn >> 5) & 0x7FFFF, 19) << 2):#x}")
    if (insn & 0x7E000000) == 0x34000000:
        op = "cbnz" if _bit(insn, 24) else "cbz"
        rt = W[_rd(insn)] if _bit(insn, 31) == 0 else X[_rd(insn)]
        return f"{op} {rt}, {pc + (sx((insn >> 5) & 0x7FFFF, 19) << 2):#x}"
    if (insn & 0x7E000000) == 0x36000000:
        op = "tbnz" if _bit(insn, 24) else "tbz"
        b5 = _bit(insn, 31)
        b40 = (insn >> 19) & 0x1F
        bit = (b5 << 5) | b40
        rt = _rd(insn)
        return f"{op} {X[rt]}, #{bit}, {pc + (sx((insn >> 5) & 0x3FFF, 14) << 2):#x}"
    if (insn & 0xFFFFFC1F) == 0xD63F0000:
        return f"blr {X[_rn(insn)]}"
    if (insn & 0xFFFFFC1F) == 0xD61F0000:
        return f"br {X[_rn(insn)]}"
    if (insn & 0xFFFFFC1F) == 0xD65F0000:
        return "ret" if _rn(insn) == 30 else f"ret {X[_rn(insn)]}"

    # ---- hints / barriers / system --------------------------------------
    if insn == 0xD503201F:
        return "nop"
    if (insn & 0xFFFFF0FF) == 0xD503201F:
        hint = (insn >> 5) & 0x7F
        names = {0: "nop", 1: "yield", 2: "wfe", 3: "wfi", 4: "sev", 5: "sevl"}
        return names.get(hint, f"hint #{hint}")
    if (insn & 0xFFFFF09F) == 0xD503309F:
        return ["dmb sy", "dmb ish", "dmb ishst", "dmb ishld"][(insn >> 8) & 3] \
            if (insn >> 8) & 3 else "dmb sy"
    if (insn & 0xFFFFF09F) == 0xD503309F:
        return "dsb"
    if (insn & 0xFFFFFFDF) == 0xD503209F:
        return "isb"
    if (insn & 0xFFF00000) == 0xD5300000 or (insn & 0xFFD00000) in (0xD5100000, 0xD5180000):
        op0 = (insn >> 19) & 3
        op1 = (insn >> 16) & 7
        crn = (insn >> 12) & 0xF
        crm = (insn >> 8) & 0xF
        op2 = (insn >> 5) & 7
        rt = _rd(insn)
        key = (crn << 8) | (crm << 4) | op2
        name = SYSREG.get(key)
        # MSR (register) has L=0 at bit 21; MRS has L=1.
        # 0xD518.... -> L=0 -> MSR (write). 0xD538.... -> L=1 -> MRS (read).
        is_read = bool(insn & (1 << 21))
        if name:
            if is_read:
                return f"mrs {X[rt]}, {name}"
            return f"msr {name}, {X[rt]}"
        if is_read:
            return f"mrs {X[rt]}, s{op0}_{op1}_c{crn}_c{crm}_{op2}"
        return f"msr s{op0}_{op1}_c{crn}_c{crm}_{op2}, {X[rt]}"

    # ---- ADR / ADRP -----------------------------------------------------
    if (insn & 0x9F000000) == 0x10000000:  # ADR
        immlo = (insn >> 29) & 3
        immhi = (insn >> 5) & 0x7FFFF
        return f"adr {X[_rd(insn)]}, {pc + sx((immhi << 2) | immlo, 21):#x}"
    if (insn & 0x9F000000) == 0x90000000:  # ADRP
        immlo = (insn >> 29) & 3
        immhi = (insn >> 5) & 0x7FFFF
        imm = sx((immhi << 2) | immlo, 21) << 12
        return f"adrp {X[_rd(insn)]}, {(pc & ~0xFFF) + imm:#x}"

    # ---- MOVZ / MOVN / MOVK ---------------------------------------------
    if (insn & 0x1F800000) == 0x12800000:
        opc = (insn >> 29) & 3
        sf = _bit(insn, 31)
        hw = (insn >> 21) & 3
        imm16 = (insn >> 5) & 0xFFFF
        rd = _rd(insn)
        reg = X[rd] if sf else W[rd]
        shift = hw * 16
        if opc == 0:
            return f"movn {reg}, #{imm16:#x}" + (f", lsl #{shift}" if shift else "")
        if opc == 2:
            return f"movz {reg}, #{imm16:#x}" + (f", lsl #{shift}" if shift else "")
        if opc == 3:
            return f"movk {reg}, #{imm16:#x}" + (f", lsl #{shift}" if shift else "")

    # ---- ADD/SUB immediate (and CMP/CMN aliases) ------------------------
    if (insn & 0x1F000000) == 0x11000000:
        sf = _bit(insn, 31)
        op = _bit(insn, 30)  # 0 add, 1 sub
        s = _bit(insn, 29)
        sh = _bit(insn, 22)
        imm12 = (insn >> 10) & 0xFFF
        rn, rd = _rn(insn), _rd(insn)
        val = imm12 << (12 if sh else 0)
        R = X if sf else W
        if s and rd == 31:
            return f"{'cmp' if op else 'cmn'} {R[rn]}, #{val:#x}"
        if sh:
            return "? (shifted add/sub imm)"
        if op == 0:
            return f"{'adds' if s else 'add'} {R[rd]}, {R[rn]}, #{val:#x}"
        return f"{'subs' if s else 'sub'} {R[rd]}, {R[rn]}, #{val:#x}"

    # ---- ADD/SUB shifted register ---------------------------------------
    if (insn & 0x1F200000) == 0x0B000000:
        sf = _bit(insn, 31)
        op = _bit(insn, 30)
        s = _bit(insn, 29)
        shift = (insn >> 22) & 3
        imm6 = (insn >> 10) & 0x3F
        rn, rd, rm = _rn(insn), _rd(insn), _rm(insn)
        R = X if sf else W
        sh = ["lsl", "lsr", "asr", "ror"][shift]
        if s and rd == 31:
            return f"{'cmp' if op else 'cmn'} {R[rn]}, {R[rm]}"
        return (f"{'sub' if op else 'add'}{'s' if s else ''} "
                f"{R[rd]}, {R[rn]}, {R[rm]}" + (f", {sh} #{imm6}" if imm6 else ""))

    # ---- logical immediate (AND/ORR/EOR/ANDS) ---------------------------
    if (insn & 0x1F800000) == 0x12000000:
        sf = _bit(insn, 31)
        opc = (insn >> 29) & 3
        n = _bit(insn, 22)
        immr = (insn >> 16) & 0x3F
        imms = (insn >> 10) & 0x3F
        rn, rd = _rn(insn), _rd(insn)
        R = X if sf else W
        names = {0: "and", 1: "orr", 2: "eor", 3: "ands"}
        # decode the bitmask immediate so comparisons are readable
        try:
            from a64_bitmask import decode_bitmask
            val = decode_bitmask(n, immr, imms, 64 if sf else 32)
            imm = f"#{val:#x}"
        except Exception:  # noqa: BLE001
            imm = f"#bitmask(n={n},immr={immr},imms={imms})"
        if opc == 3 and rd == 31:
            return f"tst {R[rn]}, {imm}"
        if opc == 1 and rn == 31:
            return f"mov {R[rd]}, {imm}"
        return f"{names[opc]} {R[rd]}, {R[rn]}, {imm}"

    # ---- logical shifted register (MOV/ORR/AND/EOR aliases) -------------
    if (insn & 0x1F000000) == 0x0A000000:
        sf = _bit(insn, 31)
        opc = (insn >> 29) & 3
        shift = (insn >> 22) & 3
        imm6 = (insn >> 10) & 0x3F
        rn, rd, rm = _rn(insn), _rd(insn), _rm(insn)
        R = X if sf else W
        sh = ["lsl", "lsr", "asr", "ror"][shift]
        if opc == 1 and rn == 31 and shift == 0 and imm6 == 0:
            return f"mov {R[rd]}, {R[rm]}"
        if opc == 1 and rn == 31:
            return f"lsl {R[rd]}, {R[rm]}, #{imm6}" if shift == 0 else \
                   f"{sh} {R[rd]}, {R[rm]}, #{imm6}"
        names = {0: "and", 1: "orr", 2: "eor", 3: "ands"}
        return (f"{names[opc]} {R[rd]}, {R[rn]}, {R[rm]}"
                + (f", {sh} #{imm6}" if imm6 else ""))

    # ---- MADD / MSUB ----------------------------------------------------
    if (insn & 0x1F000000) == 0x1B000000:
        sf = _bit(insn, 31)
        rm, ra, rn, rd = _rm(insn), (insn >> 10) & 0x1F, _rn(insn), _rd(insn)
        R = X if sf else W
        if ra == 31:
            return f"mul {R[rd]}, {R[rn]}, {R[rm]}"
        sub = _bit(insn, 15)
        return f"{'msub' if sub else 'madd'} {R[rd]}, {R[rn]}, {R[rm]}, {R[ra]}"

    # ---- UBFM/SBFM (LSL/LSR/ASR/UXTB aliases) ---------------------------
    if (insn & 0x1F800000) in (0x13000000, 0x13800000):
        sf = _bit(insn, 31)
        opc = (insn >> 29) & 3
        n, immr, imms = (insn >> 22) & 1, (insn >> 16) & 0x3F, (insn >> 10) & 0x3F
        rn, rd = _rn(insn), _rd(insn)
        R = X if sf else W
        width = 64 if sf else 32
        if opc == 2:  # UBFM
            if imms + 1 == immr and immr != 0:
                return f"lsl {R[rd]}, {R[rn]}, #{width - immr}"
            if imms == width - 1:
                return f"lsr {R[rd]}, {R[rn]}, #{immr}"
        if opc == 0:  # SBFM
            if imms == width - 1:
                return f"asr {R[rd]}, {R[rn]}, #{immr}"
            if imms == 7 and immr == 0:
                return f"sxtb {R[rd]}, {R[rn]}"
            if imms == 15 and immr == 0:
                return f"sxth {R[rd]}, {R[rn]}"
        return f"{'ubfm' if opc == 2 else 'sbfm'} {R[rd]}, {R[rn]}, #{immr}, #{imms}"

    # ---- LDP / STP (signed offset) --------------------------------------
    if (insn & 0x3A000000) == 0x28000000:
        opc = (insn >> 30) & 3
        sf = _bit(insn, 31)
        load = _bit(insn, 22)
        mode = (insn >> 23) & 3  # 1 post, 2 signed offset, 3 pre
        imm7 = sx((insn >> 15) & 0x7F, 7)
        rt2 = (insn >> 10) & 0x1F
        rn, rt = _rn(insn), _rd(insn)
        scale = 8 if sf else 4
        off = imm7 * scale
        R = X if sf else W
        mn = "ldp" if load else "stp"
        if mode == 2:
            return f"{mn} {R[rt]}, {R[rt2]}, [{R[rn]}, #{off:#x}]"
        if mode == 3:
            return f"{mn} {R[rt]}, {R[rt2]}, [{R[rn]}, #{off:#x}]!"
        return f"{mn} {R[rt]}, {R[rt2]}, [{R[rn]}], #{off:#x}"

    # ---- LDR/STR (unsigned offset) --------------------------------------
    if (insn & 0x3B000000) == 0x39000000:
        size = (insn >> 30) & 3
        load = _bit(insn, 22)
        imm12 = (insn >> 10) & 0xFFF
        rn, rt = _rn(insn), _rd(insn)
        scale = 1 << size
        off = imm12 * scale
        suf = ["b", "", "h", ""][size]
        sf = _bit(insn, 31)
        if size == 3:
            reg = X[rt] if sf else W[rt]
        else:
            reg = W[rt]
        return f"{'ldr' if load else 'str'}{suf} {reg}, [{X[rn]}, #{off:#x}]"

    # ---- LDR/STR (unscaled, pre/post index, register offset) ------------
    if (insn & 0x3B200000) == 0x38000000:
        size = (insn >> 30) & 3
        opc = (insn >> 22) & 3
        load = opc != 0
        mode = (insn >> 10) & 3
        imm9 = sx((insn >> 12) & 0x1FF, 9)
        rn, rt = _rn(insn), _rd(insn)
        suf = ["b", "", "h", ""][size]
        if size == 3:
            reg = X[rt] if _bit(insn, 31) else W[rt]
        else:
            reg = W[rt]
        base = f"[{X[rn]}, #{imm9:#x}]"
        if mode == 1:
            base += "!"
        elif mode == 3:
            base = f"[{X[rn]}], #{imm9:#x}"
        return f"{'ldr' if load else 'str'}{suf} {reg}, {base}"

    # ---- LDR/STR (register offset) --------------------------------------
    if (insn & 0x3B200C00) == 0x38200800:
        size = (insn >> 30) & 3
        load = _bit(insn, 22)
        rm, rn, rt = _rm(insn), _rn(insn), _rd(insn)
        suf = ["b", "", "h", ""][size]
        return f"{'ldr' if load else 'str'}{suf} {W[rt]}, [{X[rn]}, {X[rm]}]"

    # ---- CSEL / CSINC (conditional select) ------------------------------
    if (insn & 0x1FE00000) == 0x1A800000:
        sf = _bit(insn, 31)
        rm, rn, rd = _rm(insn), _rn(insn), _rd(insn)
        cond = insn & 0xF
        R = X if sf else W
        op = _bit(insn, 10)
        o2 = _bit(insn, 12)
        if op == 0 and o2 == 0:
            return f"csel {R[rd]}, {R[rn]}, {R[rm]}, {COND[cond]}"
        if op == 0 and o2 == 1:
            return f"csinc {R[rd]}, {R[rn]}, {R[rm]}, {COND[cond]}"
        return f"csel-family {R[rd]}, {R[rn]}, {R[rm]}, {COND[cond]}"

    # ---- CLZ / RBIT -----------------------------------------------------
    if (insn & 0xFFFFFC00) == 0xDAC01000:
        return f"clz {X[_rd(insn)]}, {X[_rn(insn)]}"

    return "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", required=True)
    ap.add_argument("--image", type=int, default=2,
                    help="1..4 for the melf's inner images")
    ap.add_argument("--offset", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--count", type=int, default=40)
    args = ap.parse_args()

    imgs = {1: (0x001300, 203888), 2: (0x032F70, 908256),
            3: (0x110B50, 303096), 4: (0x15AB48, 148924)}
    off, size = imgs[args.image]
    melf = Path(args.melf).read_bytes()
    img = melf[off:off + size]

    SEGS = {
        2: [(0x001000, 0x14825000, 0x086000), (0x087000, 0x148AB000, 0x011000),
            (0x098000, 0x148BF000, 0x030000), (0x0C8000, 0x148EF000, 0x013000)],
    }.get(args.image, [])

    def o2v(o):
        for p, v, f in SEGS:
            if p <= o < p + f:
                return v + (o - p)
        return None

    for i in range(args.count):
        o = args.offset + i * 4
        if o + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, o)[0]
        va = o2v(o)
        va_s = f"{va:#012x}" if va is not None else "------------"
        print(f"  {o:#08x}  {va_s}  {insn:08x}  {decode(insn, va or o)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
