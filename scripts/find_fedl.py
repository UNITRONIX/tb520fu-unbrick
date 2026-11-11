#!/usr/bin/env python3
"""find_fedl.py - locate and decode boot_fedl_check in the XBL core.

Why this exists
---------------
The goal of the current sessions is one state: HELLO ver=3 mode=0 from PBL.
Two routes reach it, and the hardware route (FEDL) is the only one that does not
depend on the firmware emitting a HELLO first. So the parameters of that route
matter more than anything else right now.

The device's own DCB declares (verified in xbl_config.elf, not in the
programmer's copy):

    /sw/boot/forced_download/feature          = 1        enabled
    /sw/boot/forced_download/check_usb_option = 1
    /sw/boot/forced_download/check_dp_timeout = 0x2710   = 10000
    /sw/boot/forced_download/ignore_pwr_key   = 0
    /sw/boot/fedl_timeout/ver                 = 1
    /sw/boot/fedl_timeout/action              = 1

10000 is a suspiciously round number for a ~50 ms poll. If it is milliseconds
then the FEDL window is ten seconds, and the "hold D+ low before power-on"
instruction becomes easy instead of marginal. That is the question this script
settles: find the code that CONSUMES check_dp_timeout and see the unit and the
loop.

Method notes, learned the hard way
----------------------------------
* The predicate at 0x1484396c lives in segment 2 (file offset 0x1000 ->
  virtual 0x14825000). Segment 1 (0x87000 -> 0x148AB000) holds the STRINGS.
  A wrong segment choice yields a coherent listing of unrelated code, which is
  how three earlier analyses went wrong.
* Strings in XBL are referenced by adrp+add across a page, so a strict
  "adrp page + imm12 == exact address" search misses references that use a
  register offset. Both forms are tried.

Usage
    python find_fedl.py --melf <ROM>/image/xbl_s_devprg_ns.melf
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a64 import decode  # noqa: E402

IMG_OFF = 0x032F70
IMG_SIZE = 908256
SEG = [(0x001000, 0x14825000, 0x086000),
       (0x087000, 0x148AB000, 0x011000),
       (0x098000, 0x148BF000, 0x030000),
       (0x0C8000, 0x148EF000, 0x013000)]


def o2v(o: int) -> int | None:
    for po, va, sz in SEG:
        if po <= o < po + sz:
            return va + (o - po)
    return None


def v2o(va: int) -> int | None:
    for po, v, sz in SEG:
        if v <= va < v + sz:
            return po + (va - v)
    return None


def strings(img: bytes, minlen: int = 4):
    for m in re.finditer(rb"[ -~]{%d,}" % minlen, img):
        yield m.start(), m.group().decode("ascii")


def adrp_target(insn: int, va: int) -> int:
    immlo = (insn >> 29) & 3
    immhi = (insn >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    return (va & ~0xFFF) + (imm << 12)


def find_string_refs(img: bytes, needle: bytes):
    """Every adrp (+ optional add/ldr) pair whose resolved address hits `needle`."""
    tgt = None
    for off, s in strings(img):
        if s.encode() == needle or s.encode().startswith(needle):
            tgt = o2v(off)
            break
    if tgt is None:
        return None, []
    refs = []
    for o in range(0x1000, len(img) - 8, 4):
        insn = struct.unpack_from("<I", img, o)[0]
        if (insn & 0x9F000000) != 0x90000000:
            continue
        va = o2v(o)
        if va is None:
            continue
        page = adrp_target(insn, va)
        nxt = struct.unpack_from("<I", img, o + 4)[0]
        if (nxt & 0xFFC00000) == 0x91000000:          # add xN, xN, #imm12
            imm12 = (nxt >> 10) & 0xFFF
            if page + imm12 == tgt:
                refs.append((va, "adrp+add exact"))
        elif (nxt & 0xFF800000) == 0x91000000:        # add with shift
            refs.append((va, "adrp+add shifted"))
    return tgt, refs


def dump(img: bytes, va: int, count: int, label: str = "") -> None:
    o = v2o(va)
    if o is None:
        print(f"  {va:#x} not mapped")
        return
    if label:
        print(f"\n--- {label} ---")
    for i in range(count):
        oo = o + i * 4
        if oo + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, oo)[0]
        v = o2v(oo)
        print(f"  {v:#012x}  {insn:08x}  {decode(insn, v or oo)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", required=True)
    ap.add_argument("--dump", type=lambda x: int(x, 0), default=None,
                    help="dump code at this virtual address")
    ap.add_argument("--count", type=int, default=60)
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG_OFF:IMG_OFF + IMG_SIZE]

    print("=" * 78)
    print("#  FEDL configuration, as the device declares it")
    print("=" * 78)
    for k in (b"/sw/boot", b"check_dp_timeout", b"check_usb_option",
              b"ignore_pwr_key", b"boot_fedl_check", b"Enter PBL EDL USB",
              b"dpGnd", b"EUD"):
        tgt, refs = find_string_refs(img, k)
        if tgt is None:
            print(f"  {k.decode():20s} not found")
        else:
            print(f"  {k.decode():20s} VA {tgt:#012x}   refs: "
                  f"{[hex(r[0]) for r in refs[:6]] or 'none (indirect or via register)'}")

    if args.dump:
        dump(img, args.dump, args.count, f"code at {args.dump:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
