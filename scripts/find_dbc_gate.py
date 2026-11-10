#!/usr/bin/env python3
"""find_dbc_gate.py - where does the battery check actually refuse to continue?

The DBC hypothesis was dismissed earlier on the grounds that a watchdog reset was
observed instead of a quiet power-down. That reasoning is sound but it does not
exclude DBC: a battery check can refuse to proceed and let the watchdog collect the
hang, which produces exactly the observed trace.

This locates the actual refusal points. The messages that would appear are known:

    "Loader dbc skipped. VBAT: %dmV"        the DBC was bypassed
    "charger is not charging and device will shut down"
    "battery recover failed"
    "No battery, Shutdown!"

If the code can reach a shutdown on a specific battery or charger condition, then
whether this unit is in that condition becomes a checkable question - and it would
explain a hang that survives a full charge, if the condition is "charger not
detected" rather than "battery empty".

Read-only, offline.

Usage
    python find_dbc_gate.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a64 import decode  # noqa: E402
from find_func_start import is_prologue, is_terminal  # noqa: E402
from image_dump import MelfImages  # noqa: E402

MESSAGES = [
    b"Loader dbc skipped",
    b"battery recover failed",
    b"charger is not charging",
    b"No battery",
    b"vsys-min-recover-mv",
    b"vbatt-min",
    b"battery-low-threshold-mv",
    b"vbat-thd-rtc-pon",
]


def sx(v: int, bits: int) -> int:
    m = 1 << (bits - 1)
    return (v ^ m) - m


def find_refs(mi, n: int, va: int):
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
    print("#  battery / charger refusal points")
    print("=" * 78)

    sites = {}
    for n in (2, 3):
        img = mi.image(n)
        for msg in MESSAGES:
            off = img.find(msg)
            if off < 0:
                print(f"\n  image {n}: {msg.decode()!r} absent")
                continue
            va = mi.off_to_va(n, off)
            refs = find_refs(mi, n, va)
            print(f"\n  image {n}: {msg.decode()!r}")
            print(f"    string {va:#x}   refs {len(refs)}")
            for r in refs:
                rva = mi.off_to_va(n, r)
                ent = entry_of(mi, n, r)
                print(f"      ref at {rva:#x}   enclosing entry "
                      f"{mi.off_to_va(n, ent) if ent else '?'}")
                sites[(n, msg)] = (r, ent)

    # disassemble around the first two refusal sites in image 2
    print("\n" + "=" * 78)
    print("#  context around the refusal messages")
    print("=" * 78)
    shown = 0
    for (n, msg), (r, ent) in sites.items():
        if n != 2 or shown >= 2:
            continue
        shown += 1
        start = max(0, r - 12 * 4)
        print(f"\n  --- {msg.decode()!r} ---")
        for off, va, insn, text in mi.disasm(2, start, 22):
            mark = "  <<<" if off == r else ""
            print(f"    {va:#012x}  {text}{mark}")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  A refusal point that calls a shutdown or loops waiting for the charger")
    print("  would let a battery condition hang boot. If such a point exists and is")
    print("  reached before USB is raised, then 'plugged in but not charging' is a")
    print("  sufficient explanation for the silence - and it would survive a full")
    print("  battery, because the trigger is charger *detection*, not charge level.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
