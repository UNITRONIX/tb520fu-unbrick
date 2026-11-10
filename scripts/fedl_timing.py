#!/usr/bin/env python3
"""fedl_timing.py - extract the forced-EDL trigger conditions from code.

The lead
--------
The boot XBL contains a named procedure for entering forced emergency download by
holding the USB D+ line low:

    qusb_dci_dp_gnd_check:
    dpGnd LOW, break
    dpGnd HIGH
    wait unplug(dpGnd LOW), (ms):
    dpGnd LOW, enter FEDL

Strings alone do not tell you what to do with a cable. Three things decide whether
an attempt can succeed:

  1. how long LOW must persist to be treated as a trigger rather than a glitch
  2. whether LOW must be present at power-on or is sampled later
  3. what the code does between sampling LOW and jumping to EDL

All three are in the instructions around the reference to each string, so this
resolves the string addresses and disassembles the surrounding code.

Read-only, offline.

Usage
    python fedl_timing.py
"""
from __future__ import annotations

import struct

from image_dump import MelfImages
from a64 import decode
from find_func_start import is_prologue, is_terminal

TARGETS = [
    (b"qusb_dci_dp_gnd_check: ", "dp_gnd check entry"),
    (b"dpGnd LOW, break", "momentary LOW"),
    (b"dpGnd HIGH", "line released"),
    (b"wait unplug(dpGnd LOW), (ms): ", "unplug wait"),
    (b"dpGnd LOW, enter FEDL", "the trigger"),
    (b"init_dp_gnd Failed", "pulldown init failure"),
]

IMG = 2


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def find_refs(mi, n: int, va: int) -> list[int]:
    img = mi.image(n)
    out = []
    page = va & ~0xFFF
    low = va & 0xFFF
    for p_off, seg_va, filesz in mi.segments(n):
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
                    if ((nxt >> 5) & 0x1F) == rd and ((nxt >> 10) & 0xFFF) == low:
                        out.append(p_off + i)
                    break
    return out


def entry_of(mi, n: int, off: int):
    img = mi.image(n)
    o = off & ~3
    while o > 0x1000:
        insn = struct.unpack_from("<I", img, o)[0]
        if is_prologue(insn):
            prev = struct.unpack_from("<I", img, o - 4)[0]
            if is_terminal(prev):
                return o
        o -= 4
    return None


def main() -> int:
    mi = MelfImages()
    print("=" * 78)
    print("#  forced-EDL trigger: where each string is used")
    print("=" * 78)

    sites = []
    for text, label in TARGETS:
        off = mi.image(IMG).find(text)
        if off < 0:
            print(f"\n  {label:<24} string absent")
            continue
        va = mi.off_to_va(IMG, off)
        refs = find_refs(mi, IMG, va)
        print(f"\n  {label}")
        print(f"    string {va:#x}   code refs: {len(refs)}")
        for r in refs:
            rva = mi.off_to_va(IMG, r)
            print(f"      code at {rva:#x}")
            sites.append((r, label))

    # disassemble around the earliest code site, which is the check routine
    if not sites:
        print("\n  no code references found")
        return 1

    sites.sort()
    start_off = sites[0][0]
    entry = entry_of(mi, IMG, start_off)
    print("\n" + "=" * 78)
    print(f"#  enclosing function of the first site (entry "
          f"{mi.off_to_va(IMG, entry) if entry else '?'})")
    print("=" * 78)

    base = entry if entry else start_off
    for i in range(120):
        off = base + i * 4
        img = mi.image(IMG)
        if off + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, off)[0]
        va = mi.off_to_va(IMG, off)
        text = decode(insn, va or 0)
        # annotate string loads
        note = ""
        if text.startswith("adrp"):
            try:
                page = int(text.split(", ")[1], 16)
                rd = text.split(",")[0].split()[1]
                for j in range(1, 5):
                    o2 = off + j * 4
                    t2 = decode(struct.unpack_from("<I", img, o2)[0],
                                (mi.off_to_va(IMG, o2) or 0))
                    if t2.startswith("add ") and t2[4:].startswith(rd + ", " + rd):
                        imm = int(t2[4:].split(", ")[2].lstrip("#"), 16)
                        s = mi.cstr(IMG, page + imm)
                        if s:
                            note = f'   ; "{s[:48]}"'
                        break
            except Exception:  # noqa: BLE001
                pass
        print(f"  {va if va else off:#012x}  {insn:08x}  {text}{note}")

    print("\n" + "=" * 78)
    print("#  WHAT TO READ OFF THIS")
    print("=" * 78)
    print("  - a loop with a counter or a delay call between the checks gives the")
    print("    required LOW duration")
    print("  - the order of the string references shows whether LOW is sampled")
    print("    before or after USB initialisation, i.e. whether it must be present")
    print("    at power-on")
    print("  - an unconditional branch to the dload entry after the LOW test is the")
    print("    trigger itself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
