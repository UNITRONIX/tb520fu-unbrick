#!/usr/bin/env python3
"""resolve_ddr_calls.py - which callee actually performs DDR init?

The ambiguity to settle
-----------------------
At 0x14831244 the code reads `/sw/boot:skip_ddr_init_in_EDL` and branches:

    0x14831258  cbnz w0, 0x148312c4     lookup failed
    0x1483125c  ldr  w8, [sp, #0x4]     the value
    ...
    0x148312a8  cbz  w8, 0x148312d0     value == 0 -> path A
    0x148312ac  ...  blr x8             value != 0 -> path B

Path A (value 0)  : bl 0x14863198 -> bl 0x1482e8a8 -> falls to 0x148312e8
Path B (value != 0): indirect blr through a vtable slot -> b 0x148312e8

and both converge at 0x148312e8, which calls 0x1482c338.

My earlier note claimed "value 0 means DDR init is skipped". That claim was an
assumption based on the property's name, not on the code. Path A executes MORE
calls than path B, which is the opposite of what a "skip" branch would normally
look like.

So which of these callees is DDR initialisation? Answer it by anchoring on the
strings: find every function in this image that references 'sbl1_ddr_init',
'do_ddr_training' or 'sbl1_wait_for_ddr_training', and compare their entry
addresses with the callees above.

Read-only, offline.

Usage
    python resolve_ddr_calls.py
"""
from __future__ import annotations

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

ANCHORS = [
    b"sbl1_ddr_init",
    b"do_ddr_training",
    b"sbl1_wait_for_ddr_training",
    b"sbl1_ddr_set_params",
    b"skip_ddr_init_in_EDL",
]

#: Callees from the property decision, to be identified.
SUSPECTS = [0x14863198, 0x1482E8A8, 0x1482C338, 0x1484EC14, 0x1482E7B8,
            0x1482E7F8, 0x14863494, 0x148262EC, 0x1482ED8C]


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def va_to_off(va: int):
    for p_off, seg_va, filesz in SEGS:
        if seg_va <= va < seg_va + filesz:
            return p_off + (va - seg_va)
    return None


def off_to_va(off: int):
    for p_off, seg_va, filesz in SEGS:
        if p_off <= off < p_off + filesz:
            return seg_va + (off - p_off)
    return None


def find_refs(img: bytes, va: int) -> list[int]:
    """Adrp+Add references to a virtual address; returns instruction file offsets."""
    out = []
    page = va & ~0xFFF
    low12 = va & 0xFFF
    for p_off, seg_va, filesz in SEGS:
        seg = img[p_off:p_off + filesz]
        for i in range(0, len(seg) - 32, 4):
            insn = struct.unpack_from("<I", seg, i)[0]
            if (insn & 0x9F000000) != 0x90000000:
                continue
            immlo = (insn >> 29) & 3
            immhi = (insn >> 5) & 0x7FFFF
            imm = sx((immhi << 2) | immlo, 21) << 12
            pc = seg_va + i
            if (pc & ~0xFFF) + imm != page:
                continue
            rd = insn & 0x1F
            for j in range(1, 9):
                o2 = i + j * 4
                if o2 + 4 > len(seg):
                    break
                nxt = struct.unpack_from("<I", seg, o2)[0]
                if (nxt & 0xFFC00000) == 0x91000000:
                    if ((nxt >> 5) & 0x1F) == rd and ((nxt >> 10) & 0xFFF) == low12:
                        out.append(p_off + i)
                        break
    return out


def find_bl_callers(img: bytes, target_va: int) -> list[int]:
    """Direct BL instructions that call target_va."""
    out = []
    for p_off, seg_va, filesz in SEGS:
        seg = img[p_off:p_off + filesz]
        for i in range(0, len(seg) - 4, 4):
            insn = struct.unpack_from("<I", seg, i)[0]
            if (insn & 0xFC000000) != 0x94000000:
                continue
            imm = sx(insn & 0x3FFFFFF, 26) << 2
            if seg_va + i + imm == target_va:
                out.append(p_off + i)
    return out


def main() -> int:
    melf = Path(DEFAULT_MELF).read_bytes()
    img = melf[IMG2_OFF:IMG2_OFF + IMG2_LEN]

    print("=" * 78)
    print("#  which code references the DDR stage strings?")
    print("=" * 78)
    anchor_va = {}
    for a in ANCHORS:
        s = img.find(a)
        if s < 0:
            print(f"  {a.decode():<32} absent")
            continue
        va = off_to_va(s)
        anchor_va[a] = va
        refs = find_refs(img, va) if va else []
        print(f"  {a.decode():<32} str@{va:#x}  refs={len(refs)}")
        for r in refs[:6]:
            print(f"      ref at image+{r:#07x}  va={off_to_va(r):#x}")

    print("\n" + "=" * 78)
    print("#  identifying the callees from the property decision")
    print("=" * 78)
    print(f"  {'callee':>14}  {'off':>9}  {'direct callers':>14}  first callers")
    print("  " + "-" * 74)
    for va in SUSPECTS:
        off = va_to_off(va)
        callers = find_bl_callers(img, va)
        shown = ", ".join(f"{off_to_va(c):#x}" for c in callers[:4])
        print(f"  {va:#14x}  {off if off is None else hex(off):>9}  "
              f"{len(callers):>14}  {shown}")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  A callee that is invoked from the DDR pipeline and that itself sits")
    print("  near the DDR stage strings is the initialisation function. Compare the")
    print("  caller addresses above with the reference sites listed first: if a")
    print("  suspect is called from the same function that references")
    print("  'sbl1_ddr_init', that settles which branch performs the work.")
    print()
    print("  Do not conclude from the property's NAME. The name says what a")
    print("  developer intended; only the branch direction says what the code does.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
