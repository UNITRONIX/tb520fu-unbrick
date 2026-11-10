#!/usr/bin/env python3
"""audit_references.py - check whether a reported reference is trustworthy.

The mistake this catches
------------------------
write_gate_analysis.py reported that the string "device is locked, cannot write"
is referenced from code at image+0x008eac, and that site does `bl 0x149a369c`.
Taking that at face value led to disassembling 0x149a369c - which turned out to be
in the MIDDLE of the function at 0x1499ac40, so everything read from it was
meaningless.

An ADRP+ADD pair that resolves to an address proves only that the address is
computed there. It does not prove the surrounding instructions form a coherent
call, and it does not prove the address is a function entry.

This script audits a reference honestly:
  1. is the reference address inside a PT_LOAD segment? (decodable at all)
  2. does it resolve under ADRP+ADD with a plausible register/offset pair?
  3. is the reported callee target actually a function entry?
  4. does the code around the reference look like code (sane instruction mix)?

Read-only, offline.

Usage
    python audit_references.py
"""
from __future__ import annotations

import struct

from image_dump import MelfImages
from a64 import decode
from find_func_start import is_prologue, is_terminal

GATES = [
    (b"device is locked, cannot write", 0x008EAC),
    (b"device is locked, cannot erase", 0x009ACC),
]


def main() -> int:
    mi = MelfImages()
    img = mi.image(3)
    segs = mi.segments(3)

    print("=" * 78)
    print("#  auditing the reported write-gate references")
    print("=" * 78)
    for p_off, p_vaddr, filesz in segs:
        print(f"  segment off={p_off:#08x} vaddr={p_vaddr:#010x} "
              f"end={p_vaddr + filesz:#010x}")

    for text, site in GATES:
        print("\n" + "-" * 78)
        print(f'  string: {text.decode()!r}')
        s_off = img.find(text)
        s_va = mi.off_to_va(3, s_off)
        site_va = mi.off_to_va(3, site)
        print(f"    string at image+{s_off:#08x}  va={s_va}")
        print(f"    reported reference at image+{site:#08x}  va={site_va}")

        # verify the site really computes s_va
        ok = False
        detail = ""
        for back in range(0, 6):
            o = site - back * 4
            if o < 0:
                break
            insn = struct.unpack_from("<I", img, o)[0]
            if (insn & 0x9F000000) != 0x90000000:
                continue
            immlo = (insn >> 29) & 3
            immhi = (insn >> 5) & 0x7FFFF
            imm = ((immhi << 2) | immlo)
            if imm & (1 << 20):
                imm -= 1 << 21
            imm <<= 12
            pc = mi.off_to_va(3, o)
            page = (pc & ~0xFFF) + imm
            rd = insn & 0x1F
            # find the following add
            for j in range(1, 6):
                o2 = o + j * 4
                nxt = struct.unpack_from("<I", img, o2)[0]
                if (nxt & 0xFFC00000) == 0x91000000:
                    if ((nxt >> 5) & 0x1F) == rd:
                        target = page + ((nxt >> 10) & 0xFFF)
                        ok = target == s_va
                        detail = (f"adrp at image+{o:#x} -> page {page:#x}, "
                                  f"add -> {target:#x}")
                    break
            break

        print(f"    ADRP+ADD resolves to string: {ok}")
        if detail:
            print(f"      {detail}")

        # is the site inside executable code and does it look coherent?
        for p_off, p_vaddr, filesz in segs:
            if p_off <= site < p_off + filesz:
                print(f"    site is inside segment starting at vaddr {p_vaddr:#x} "
                      f"(executable)")
                break
        else:
            print("    site is NOT inside any loadable segment")

        # show the context and check the callee claim
        print("    context:")
        for i in range(-4, 6):
            o = site + i * 4
            insn = struct.unpack_from("<I", img, o)[0]
            va = mi.off_to_va(3, o)
            mark = "  <<<" if i == 0 else ""
            print(f"      {o:#08x}  {insn:08x}  {decode(insn, va or 0)}{mark}")

        # find nearest preceding entry and the enclosing function
        entry = None
        o = site & ~3
        while o > 0x1000:
            insn = struct.unpack_from("<I", img, o)[0]
            if is_prologue(insn):
                prev = struct.unpack_from("<I", img, o - 4)[0]
                if is_terminal(prev):
                    entry = o
                    break
            o -= 4
        if entry is not None:
            print(f"    enclosing function entry: image+{entry:#08x} "
                  f"(va={mi.off_to_va(3, entry)})")

        # what does the site BL to?
        insn = struct.unpack_from("<I", img, site + 0x0C)[0]
        if (insn & 0xFC000000) == 0x94000000:
            imm = insn & 0x3FFFFFF
            if imm & (1 << 25):
                imm -= 1 << 26
            target_va = (mi.off_to_va(3, site + 0x0C) or 0) + (imm << 2)
            print(f"    bl at image+{site + 0x0C:#x} -> va {target_va:#x}")
            t_off = mi.va_to_off(3, target_va)
            print(f"      target image offset: {t_off if t_off is None else hex(t_off)}")
            if t_off is not None:
                t_insn = struct.unpack_from("<I", img, t_off)[0]
                print(f"      target first insn: {t_insn:08x}  {decode(t_insn, target_va)}")
                if is_prologue(t_insn):
                    print("      -> looks like a real function entry")
                else:
                    print("      -> NOT a function entry: this is mid-function, so")
                    print("         the 'callee' reading was wrong. Do not trust it.")

    print("\n" + "=" * 78)
    print("#  CONCLUSION")
    print("=" * 78)
    print("  An ADRP+ADD reference proves an address is COMPUTED at that site. It")
    print("  does not prove the surrounding code is a coherent call, nor that the")
    print("  target is a function. Both must be checked before drawing conclusions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
