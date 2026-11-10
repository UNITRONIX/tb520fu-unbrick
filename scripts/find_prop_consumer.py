#!/usr/bin/env python3
"""find_prop_consumer.py - locate the code that reads a device-tree property.

Why this is the next step
-------------------------
The devprg contains the string `skip_ddr_init_in_EDL`. There is code whose whole
purpose is to not re-train DDR during EDL - and DDR is demonstrably already up,
because the crash-dump handler is running on it.

So the question that decides the whole approach is: where is that property read,
and by what? Answering it turns "the programmer probably hangs in DDR bring-up"
into a specific instruction sequence we can reason about - or into a dead end we
can state as a fact.

How the search works
--------------------
The property name is a string in the ELF's rodata. ARM64 code reaches it with a
PC-relative pair:

    ADRP  Xd, <page of string>
    ADD   Xd, Xd, #<offset within page>

so an ADRP whose computed page matches the string's page, followed shortly by an
ADD with the right 12-bit immediate and the same register, is a reference. The
same address may also appear as an absolute 64-bit pointer in a table, so that is
searched for too.

Both images that contain the string are checked: the XBL core (image [2]) and the
shrm DDR module (image [4]).

Read-only, offline.

Usage
    python find_prop_consumer.py
    python find_prop_consumer.py --string skip_ddr_init_in_EDL
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)

#: (label, file offset, size) of the melf's inner images, per docs/04.
IMAGES = [
    ("xbl_core", 0x032F70, 908256),
    ("shrm", 0x15AB48, 148924),
]


def sign_extend(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def load_phdrs(img: bytes):
    """Return [(p_offset, p_vaddr, p_filesz)] for a 64-bit ELF image."""
    if img[:4] != b"\x7fELF" or img[4] != 2:
        return []
    e_phoff = struct.unpack_from("<Q", img, 32)[0]
    e_phnum = struct.unpack_from("<H", img, 56)[0]
    out = []
    for i in range(e_phnum):
        o = e_phoff + i * 56
        if o + 56 > len(img):
            break
        p_type = struct.unpack_from("<I", img, o)[0]
        p_off, p_vaddr, _pa, p_filesz, _m = struct.unpack_from("<QQQQQ", img, o + 8)
        if p_type == 1 and p_filesz:
            out.append((p_off, p_vaddr, p_filesz))
    return out


def off_to_vaddr(phdrs, off: int):
    for p_off, p_vaddr, filesz in phdrs:
        if p_off <= off < p_off + filesz:
            return p_vaddr + (off - p_off)
    return None


def find_adrp_add(img: bytes, phdrs, target_va: int) -> list[tuple[int, int, int]]:
    """Return [(file_off_of_adrp, adrp_insn, add_insn)] for references to target_va."""
    hits = []
    page = target_va & ~0xFFF
    low12 = target_va & 0xFFF

    for p_off, p_vaddr, filesz in phdrs:
        seg = img[p_off:p_off + filesz]
        # scan every 4-byte aligned instruction in the executable segment
        for i in range(0, len(seg) - 32, 4):
            insn = struct.unpack_from("<I", seg, i)[0]
            # ADRP: op=1, bits 28..24 = 10000
            if (insn & 0x9F000000) != 0x90000000:
                continue
            immlo = (insn >> 29) & 0x3
            immhi = (insn >> 5) & 0x7FFFF
            imm = sign_extend((immhi << 2) | immlo, 21) << 12
            pc = p_vaddr + i
            adrp_target = (pc & ~0xFFF) + imm
            if adrp_target != page:
                continue
            rd = insn & 0x1F
            # look ahead a few instructions for ADD Xd, Xd, #low12
            for j in range(1, 9):
                o2 = i + j * 4
                if o2 + 4 > len(seg):
                    break
                nxt = struct.unpack_from("<I", seg, o2)[0]
                if (nxt & 0xFFC00000) == 0x91000000:  # ADD (immediate)
                    imm12 = (nxt >> 10) & 0xFFF
                    rn = (nxt >> 5) & 0x1F
                    if rn == rd and imm12 == low12:
                        hits.append((p_off + i, insn, nxt))
                        break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    ap.add_argument("--string", default="skip_ddr_init_in_EDL")
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    melf = path.read_bytes()
    needle = args.string.encode()

    print("=" * 78)
    print(f'#  who reads "{args.string}"?')
    print("=" * 78)

    total_hits = 0
    for label, off, size in IMAGES:
        img = melf[off:off + size]
        s = img.find(needle)
        print(f"\n--- image [{label}]  {off:#x}..{off + size:#x}")
        if s < 0:
            print("    string absent")
            continue

        phdrs = load_phdrs(img)
        print(f"    string @ image+{s:#x}  ({len(phdrs)} loadable segments)")
        for p_off, p_vaddr, filesz in phdrs:
            print(f"      seg off={p_off:#08x} vaddr={p_vaddr:#010x} filesz={filesz:#08x}")

        va = off_to_vaddr(phdrs, s)
        if va is None:
            print("    cannot map string offset to a virtual address")
            continue
        print(f"    string virtual address: {va:#x}")

        # absolute pointer table?
        ptr = struct.pack("<Q", va)
        n_ptr = img.count(ptr)
        print(f"    absolute 64-bit pointers to it: {n_ptr}")
        if n_ptr:
            pos = 0
            for _ in range(min(n_ptr, 8)):
                k = img.find(ptr, pos)
                pos = k + 1
                print(f"      pointer at image+{k:#x}")

        hits = find_adrp_add(img, phdrs, va)
        print(f"    ADRP+ADD references: {len(hits)}")
        for fo, a, b in hits:
            print(f"      image+{fo:#08x}  adrp={a:#010x}  add={b:#010x}")
        total_hits += len(hits) + n_ptr

    print("\n" + "=" * 78)
    print("#  RESULT")
    print("=" * 78)
    print(f"  total references found: {total_hits}")
    if total_hits:
        print("  => the property is consumed by real code, not merely named. The")
        print("     reference sites above are where the EDL-skip decision is made.")
        print("     Next: disassemble around them to see which config source is")
        print("     consulted (DT property vs SMEM key) and what value skips init.")
    else:
        print("  => no ADRP+ADD and no pointer. The string exists but is not")
        print("     referenced PC-relatively in these images, which most likely")
        print("     means it is looked up through a generic property interface")
        print("     (the name is passed to a DT lookup routine as data, reached via")
        print("     a name table rather than by direct address).")
        print("     In that case the decision logic cannot be located by string")
        print("     reference alone, and this approach has reached its limit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
