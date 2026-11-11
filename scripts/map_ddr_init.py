#!/usr/bin/env python3
"""map_ddr_init.py - map sbl1_ddr_init: control flow, vtable calls, bail-out paths.

Why
---
docs/16 s7 reduces the whole failure to one gap: the programmer's `main` calls
DDR initialisation and never speaks again. The gap is inside the function at
0x1482e8a8 (image[2] offset 0xa8a8). This tool reads that function statically so
the gap becomes a list of named decisions instead of a black box.

What it reports
---------------
  * the function's extent (entry to the final `ret`)
  * every branch and its target, with the target's role classified
  * every indirect call (`blr xN`) - these go through the DDR operation tables in
    the config struct, so each one is a named step whose failure is silent from
    outside
  * every path that reaches the error return at 0x1482e8f8
  * the string each logging call is given, which names the step being entered

The point is to find WHICH step the code is sitting in when it stops advancing,
using only what is on disk.

Usage
    python map_ddr_init.py --melf <ROM>/image/xbl_s_devprg_ns.melf
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a64 import decode  # noqa: E402

IMG_OFF = 0x032F70      # image[2], XBL core
IMG_SIZE = 908256
SEG = [(0x001000, 0x14825000, 0x086000), (0x087000, 0x148AB000, 0x011000),
       (0x098000, 0x148BF000, 0x030000), (0x0C8000, 0x148EF000, 0x013000)]

FUNC = 0x1482e8a8
ERR_RET = 0x1482e8f8


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


def read_str(img: bytes, va: int, limit: int = 72) -> str:
    o = v2o(va)
    if o is None:
        return ""
    end = img.find(b"\x00", o, o + limit)
    if end < 0:
        return ""
    raw = img[o:end]
    if len(raw) < 3 or not all(32 <= b < 127 for b in raw):
        return ""
    return raw.decode("ascii", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", required=True)
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG_OFF:IMG_OFF + IMG_SIZE]

    start = v2o(FUNC)
    if start is None:
        print("function not inside a mapped segment")
        return 1

    print("=" * 78)
    print(f"#  sbl1_ddr_init @ {FUNC:#x}   (image[2] offset {start:#x})")
    print("=" * 78)

    insns: list[tuple[int, int, str]] = []
    o = start
    # Walk until the last `ret` that closes a prologue we saw; 0x400 bytes is
    # comfortably past the epilogue at 0xa908 plus the tail blocks.
    for _ in range(0x400 // 4):
        if o + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, o)[0]
        va = o2v(o)
        txt = decode(insn, va or o)
        insns.append((o, insn, txt))
        o += 4
        # stop a little after the error epilogue
        if len(insns) > 40 and txt == "ret" and insns[-1][0] > 0xa8a8:
            # keep going only while code follows a branch; a ret here usually
            # ends the epilogue, but tail blocks sit after it, so continue to a
            # fixed bound instead of stopping on the first ret.
            pass

    # ---- classify branches ------------------------------------------------
    branches = []
    vcalls = []
    logs = []
    for off, insn, txt in insns:
        va = o2v(off)
        if txt.startswith(("b ", "b.", "cbz", "cbnz", "tbz", "tbnz", "bl ")) and "#" not in txt:
            pass
        # direct branch / call
        for mn in ("b ", "bl ", "b.eq", "b.ne", "b.hi", "b.ls", "b.cs", "b.cc",
                   "b.mi", "b.pl", "b.gt", "b.le", "b.ge", "b.lt", "cbz", "cbnz",
                   "tbz", "tbnz"):
            if txt.startswith(mn):
                tgt = txt.rsplit(" ", 1)[-1]
                branches.append((va, txt, tgt))
                break
        if txt.startswith("blr "):
            vcalls.append((va, txt))
        # adrp+add -> string pointer used as an argument
        if txt.startswith("adrp "):
            try:
                page = int(txt.split(", ")[1], 16)
            except Exception:  # noqa: BLE001
                page = None
            if page is not None:
                # look a couple of instructions ahead for "add xN, xN, #imm"
                idx = insns.index((off, insn, txt))
                for j in range(idx + 1, min(idx + 3, len(insns))):
                    t2 = insns[j][2]
                    if t2.startswith("add ") and t2.endswith("]") is False and ", #0x" in t2:
                        try:
                            imm = int(t2.rsplit("#", 1)[1], 16)
                        except Exception:  # noqa: BLE001
                            continue
                        s = read_str(img, page + imm)
                        if s:
                            logs.append((va, page + imm, s))
                        break

    print(f"\ninstructions decoded: {len(insns)}")
    print(f"indirect calls (blr): {len(vcalls)}")
    print(f"direct branches: {len(branches)}")

    print("\n--- strings this function points at (they name the steps) ---")
    seen = set()
    for va, addr, s in logs:
        if s in seen:
            continue
        seen.add(s)
        print(f"  {va:#012x} -> {addr:#012x}  {s!r}")

    print("\n--- bail-out paths (branches to the error return) ---")
    to_err = [(va, t) for va, t, tgt in branches
              if tgt.lower().endswith(f"{ERR_RET:#x}")]
    print(f"  {len(to_err)} branches reach {ERR_RET:#x}")
    for va, t in to_err:
        print(f"    {va:#012x}  {t}")

    print("\n--- indirect calls, in address order ---")
    for va, t in vcalls:
        print(f"    {va:#012x}  {t}")

    print("\n--- full listing ---")
    for off, insn, txt in insns:
        va = o2v(off)
        mark = ""
        if txt.startswith("bl "):
            mark = "  <-- call"
        elif txt.startswith("blr "):
            mark = "  <-- vtable call"
        elif txt == "ret":
            mark = "  <-- RETURN"
        print(f"  {va:#012x}  {insn:08x}  {txt}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
