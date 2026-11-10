#!/usr/bin/env python3
"""watchdog_map.py - where the watchdog is handled, and what could stop it.

Context
-------
No single delay in the programmer is anywhere near 8 s (find_8s_loops.py: the only
one above 50 ms is 50 ms, in XBL). So the observed 8.016 s is not a designed wait -
it is the watchdog window (7.918 s +/- 3 ms) plus ~98 ms of work.

That means the programmer ran, did something for about a tenth of a second, and then
stopped making progress. The question worth asking is therefore not "what sleeps for
8 s" but "where does the code stop servicing the watchdog".

This maps the watchdog surface: every string and the code that references it, in
both the XBL core and the Firehose image.

Read-only, offline.

Usage
    python watchdog_map.py
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_dump import MelfImages  # noqa: E402
from find_func_start import is_prologue, is_terminal  # noqa: E402

PATS = [b"wdog", b"WDOG", b"WDog", b"watchdog", b"Watchdog",
        b"WatchDogTimerLib", b"WDT", b"wdt"]


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def refs(mi, n: int, va: int):
    img = mi.image(n)
    out = []
    page, low = va & ~0xFFF, va & 0xFFF
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
    print("#  watchdog surface")
    print("=" * 78)

    for n in (2, 3):
        img = mi.image(n)
        print(f"\n--- image [{n}]")
        seen = set()
        for pat in PATS:
            start = 0
            while True:
                k = img.find(pat, start)
                if k < 0:
                    break
                start = k + 1
                # extract the full printable run containing the pattern
                s = k
                while s > 0 and 32 <= img[s - 1] < 127:
                    s -= 1
                e = k
                while e < len(img) and 32 <= img[e] < 127:
                    e += 1
                text = img[s:e].decode("ascii", "replace")
                if not text or text in seen:
                    continue
                seen.add(text)
                va = mi.off_to_va(n, s)
                r = refs(mi, n, va) if va is not None else []
                where = ", ".join(
                    f"{mi.off_to_va(n, x):#x}" for x in r[:3]) or "no direct refs"
                print(f"  {va if va else s:#012x}  {text[:60]:<62} {where}")

    # ---- follow WatchDogTimerLib, which names the library --------------
    print("\n" + "=" * 78)
    print("#  the watchdog library")
    print("=" * 78)
    img = mi.image(2)
    k = img.find(b"WatchDogTimerLib.c")
    if k >= 0:
        va = mi.off_to_va(2, k)
        print(f"  'WatchDogTimerLib.c' @ {va:#x}")
        rs = refs(mi, 2, va)
        print(f"  referenced from {len(rs)} site(s):")
        for r in rs:
            rva = mi.off_to_va(2, r)
            ent = entry_of(mi, 2, r)
            print(f"    {rva:#x}   enclosing entry "
                  f"{mi.off_to_va(2, ent) if ent else '?'}")
    else:
        print("  not present in image 2")

    print("\n" + "=" * 78)
    print("#  WHAT THIS IS FOR")
    print("=" * 78)
    print("  A hang is not 'code waiting 8 s'; it is 'code that stopped advancing'.")
    print("  The places that reference the watchdog library are the candidates for")
    print("  where servicing should happen. If the programmer blocks in a call that")
    print("  never returns, no further servicing occurs and the window expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
