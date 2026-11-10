#!/usr/bin/env python3
"""resolve_strings.py - map the string addresses used by the DDR pipeline.

The disassembly of the DDR-init function (0x1482e8a8) is full of ADRP+ADD pairs
that build string pointers. Those strings are the messages the code prints, so
resolving them turns an instruction listing into a readable procedure.

This resolves a given list of virtual addresses (or every ADRP+ADD pair in a
function) to the string they point at.

Read-only, offline.

Usage
    python resolve_strings.py --function 0xa8a8 --count 200
    python resolve_strings.py --va 0x148abc1c --va 0x148abe31
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)
IMG_OFF, IMG_LEN = 0x032F70, 908256
SEGS = [
    (0x001000, 0x14825000, 0x086000),
    (0x087000, 0x148AB000, 0x011000),
    (0x098000, 0x148BF000, 0x030000),
    (0x0C8000, 0x148EF000, 0x013000),
]


def va_to_off(va: int):
    for p_off, seg_va, filesz in SEGS:
        if seg_va <= va < seg_va + filesz:
            return p_off + (va - seg_va)
    return None


def read_cstr(img: bytes, va: int, maxlen: int = 200) -> str | None:
    off = va_to_off(va)
    if off is None:
        return None
    end = img.find(b"\x00", off, off + maxlen)
    if end < 0:
        return None
    raw = img[off:end]
    if not raw:
        return ""
    # only accept if it looks like text
    printable = sum(1 for c in raw if 32 <= c < 127)
    if printable / len(raw) < 0.90:
        return None
    return raw.decode("ascii", "replace")


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    ap.add_argument("--function", type=lambda x: int(x, 0), default=None,
                    help="image offset of a function to scan for ADRP+ADD strings")
    ap.add_argument("--count", type=int, default=200, help="instructions to scan")
    ap.add_argument("--va", type=lambda x: int(x, 0), action="append", default=[],
                    help="resolve a specific VA (repeatable)")
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG_OFF:IMG_OFF + IMG_LEN]

    if args.va:
        for v in args.va:
            s = read_cstr(img, v)
            print(f"  {v:#012x}  {s!r}" if s is not None else f"  {v:#012x}  <not a string / unmapped>")
        return 0

    if args.function is None:
        print("give --function or --va")
        return 2

    print("=" * 78)
    print(f"#  strings referenced from image+{args.function:#x}")
    print("=" * 78)

    pending_page = None
    pending_reg = None
    results = []
    for i in range(args.count):
        off = args.function + i * 4
        if off + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, off)[0]
        # need the VA for PC-relative maths
        va = None
        for p_off, seg_va, filesz in SEGS:
            if p_off <= off < p_off + filesz:
                va = seg_va + (off - p_off)
                break
        if va is None:
            continue

        if (insn & 0x9F000000) == 0x90000000:
            immlo = (insn >> 29) & 3
            immhi = (insn >> 5) & 0x7FFFF
            imm = sx((immhi << 2) | immlo, 21) << 12
            pending_page = (va & ~0xFFF) + imm
            pending_reg = insn & 0x1F
            continue

        if (insn & 0xFFC00000) == 0x91000000 and pending_page is not None:
            imm12 = (insn >> 10) & 0xFFF
            sh = (insn >> 22) & 1
            rn = (insn >> 5) & 0x1F
            if rn == pending_reg:
                target = pending_page + (imm12 << (12 if sh else 0))
                s = read_cstr(img, target)
                if s:
                    results.append((va, target, s))
                pending_page = None
                pending_reg = None

    for site, target, s in results:
        print(f"  {site:#012x}  -> {target:#012x}  {s!r}")

    print(f"\n  {len(results)} strings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
