#!/usr/bin/env python3
"""write_gate_analysis.py - what actually gates writing in the programmer?

The finding that reframes everything
------------------------------------
Firehose implements the full write path:

    program   WRITE to storage
    erase     ERASE storage
    patch     raw memory patches
    poke      write memory
    <data>    the XML payload element

and it carries two refusal strings:

    "device is locked, cannot write"
    "device is locked, cannot erase"

So "we cannot write to this tablet" was never about the tooling or the protocol.
The programmer can write. Something makes it decide the device is locked.

This matters because the whole recovery plan - paying for a board swap, or a
test-point - assumes write access is unavailable. If the gate is a condition we
can satisfy or bypass, the tablet is recoverable without either.

What this script does
---------------------
Locates the gate strings, finds the code that reaches them, and reports what is
compared. It answers: is the gate a fuse, a partition flag, a policy value, or an
assertion the host can influence?

Read-only, offline.

Usage
    python write_gate_analysis.py
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)
IMG3_OFF, IMG3_LEN = 0x110B50, 303096

GATES = [
    b"device is locked, cannot write",
    b"device is locked, cannot erase",
    b"No configuration/provisioning allowed for this device type",
    b"Peek is disabled on secure boot devices",
]

#: Related policy / lock vocabulary to correlate with.
POLICY = [
    "secure", "Secure", "SECURE", "lock", "Lock", "LOCK",
    "fuse", "Fuse", "FUSE", "qsee", "QSEE", "tz", "TZ",
    "provision", "Provision", "provisioning",
    "oem", "OEM", "debug", "Debug", "DEBUG",
    "unlocked", "Unlocked", "unlock",
]


def load_phdrs(img: bytes):
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


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG3_OFF:IMG3_OFF + IMG3_LEN]
    phdrs = load_phdrs(img)

    print("=" * 78)
    print("#  the write gate in Firehose")
    print("=" * 78)
    print(f"  image [3]  {IMG3_LEN} B   {len(phdrs)} loadable segments")
    for p_off, p_vaddr, filesz in phdrs:
        print(f"    off={p_off:#08x} vaddr={p_vaddr:#010x} filesz={filesz:#08x}")

    def off_to_va(off: int):
        for p_off, p_vaddr, filesz in phdrs:
            if p_off <= off < p_off + filesz:
                return p_vaddr + (off - p_off)
        return None

    # ---- locate the gate strings and the code that references them ------
    print("\n#  gate strings and their referencing sites")
    for g in GATES:
        i = img.find(g)
        if i < 0:
            print(f"\n  {g.decode()!r}: absent")
            continue
        va = off_to_va(i)
        print(f"\n  {g.decode()!r}")
        print(f"    string image+{i:#08x}  va={va}")

        refs = []
        if va is not None:
            page = va & ~0xFFF
            low12 = va & 0xFFF
            for p_off, p_vaddr, filesz in phdrs:
                seg = img[p_off:p_off + filesz]
                for k in range(0, len(seg) - 32, 4):
                    insn = struct.unpack_from("<I", seg, k)[0]
                    if (insn & 0x9F000000) != 0x90000000:
                        continue
                    immlo = (insn >> 29) & 3
                    immhi = (insn >> 5) & 0x7FFFF
                    imm = sx((immhi << 2) | immlo, 21) << 12
                    pc = p_vaddr + k
                    if (pc & ~0xFFF) + imm != page:
                        continue
                    rd = insn & 0x1F
                    for j in range(1, 9):
                        o2 = k + j * 4
                        if o2 + 4 > len(seg):
                            break
                        nxt = struct.unpack_from("<I", seg, o2)[0]
                        if (nxt & 0xFFC00000) == 0x91000000:
                            if ((nxt >> 5) & 0x1F) == rd and ((nxt >> 10) & 0xFFF) == low12:
                                refs.append(p_off + k)
                                break
        print(f"    ADRP+ADD references: {len(refs)}")
        for r in refs[:6]:
            print(f"      code at image+{r:#08x}  va={off_to_va(r)}")

    # ---- policy vocabulary, grouped ------------------------------------
    print("\n#  policy / lock vocabulary present in the image")
    counts = {}
    for term in POLICY:
        n = len(re.findall(term.encode(), img))
        if n:
            counts[term] = n
    for term, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {term:<14} x{n}")

    # ---- does it consult a security state it cannot change? ------------
    print("\n#  security-state strings that suggest where the decision comes from")
    interesting = []
    for m in re.finditer(rb"[\x20-\x7e]{12,}", img):
        s = m.group().decode("ascii", "replace")
        low = s.lower()
        if any(k in low for k in ("secure boot", "islocked", "is_locked", "locked",
                                  "debug", "provision", "fuse", "oem",
                                  "not allowed", "denied", "cannot")):
            a = sum(c.isalpha() or c in " _:=-%.,()/" for c in s) / len(s)
            if a > 0.75:
                interesting.append((IMG3_OFF + m.start(), s))
    seen = set()
    for off, s in interesting:
        if s in seen:
            continue
        seen.add(s)
        print(f"  {off:#08x}  {s[:110]}")

    print("\n" + "=" * 78)
    print("#  WHAT THIS MEANS")
    print("=" * 78)
    print("  The write path exists and is complete: program, erase, patch, poke.")
    print("  The refusal is conditional - 'device is locked, cannot write' is a")
    print("  message produced by a test, not by a missing implementation.")
    print()
    print("  Two very different worlds follow:")
    print("   a) the gate reads a hardware fuse or a hardware-rooted security")
    print("      state, in which case no host-side action changes it;")
    print("   b) the gate reads a software flag from a partition, in which case")
    print("      the state was set by what happened to this tablet and can, in")
    print("      principle, be unset.")
    print()
    print("  The reference sites above are where that decision is made. Reading")
    print("  them answers which world we are in - which is the single most")
    print("  consequential unknown left.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
