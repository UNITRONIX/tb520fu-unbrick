#!/usr/bin/env python3
"""predicate_analysis.py - read the lock predicate at 0x149a369c honestly.

Established facts
-----------------
Two distinct write paths consult the same predicate:

    write path:  0x8ea0  bl 0x149a369c
                 0x8ea4  cmp w0, #0x1
                 0x8ea8  b.ne allow          ; w0 != 1 -> writing proceeds
                 0x8eac  "...cannot write"

    erase path:  0x9ac0  bl 0x149a369c
                 0x9ac4  cmp w0, #0x1
                 0x9ac8  b.ne allow
                 0x9acc  "...cannot erase"

So the predicate returns exactly 1 when the device is locked, and anything else
otherwise. Whatever it examines is the single decision point for all storage
mutation.

What went wrong last time
-------------------------
0x149a369c was reported as a function entry and it is not: disassembling from it
produced nonsense. The correct approach is to find the enclosing function and read
the predicate as a block, noting that a `bl` target can legitimately be a shared
tail or a local label.

This disassembles around 0x149a369c from the nearest real entry, resolves its
string references, and reports what value would have to change for the write to be
allowed.

Read-only, offline.

Usage
    python predicate_analysis.py
"""
from __future__ import annotations

import struct

from image_dump import MelfImages
from a64 import decode
from find_func_start import is_prologue, is_terminal

PRED_VA = 0x149A369C


def main() -> int:
    mi = MelfImages()
    img = mi.image(3)

    pred_off = mi.va_to_off(3, PRED_VA)
    print("=" * 78)
    print(f"#  the lock predicate at va {PRED_VA:#x} (image+{pred_off:#x})")
    print("=" * 78)

    # nearest preceding real entry
    entry = None
    o = pred_off & ~3
    while o > 0x1000:
        insn = struct.unpack_from("<I", img, o)[0]
        if is_prologue(insn):
            prev = struct.unpack_from("<I", img, o - 4)[0]
            if is_terminal(prev):
                entry = o
                break
        o -= 4
    print(f"  enclosing entry: image+{entry:#08x}  va={mi.off_to_va(3, entry)}")
    print(f"  offset of predicate from that entry: "
          f"{pred_off - entry:#x} bytes ({(pred_off - entry)//4} instructions)")

    # read the predicate itself in context
    start = pred_off - 0x40
    print(f"\n#  instructions around the predicate "
          f"(from image+{start:#08x})")
    rows = []
    for i in range(40):
        o = start + i * 4
        insn = struct.unpack_from("<I", img, o)[0]
        va = mi.off_to_va(3, o)
        rows.append((o, va, insn, decode(insn, va if va is not None else o)))

    # resolve adrp+add strings
    resolved = {}
    for idx, (o, va, insn, text) in enumerate(rows):
        if not text.startswith("adrp"):
            continue
        try:
            page = int(text.split(", ")[1], 16)
        except Exception:  # noqa: BLE001
            continue
        rd = text.split(",")[0].split()[1]
        for j in range(idx + 1, min(idx + 6, len(rows))):
            t2 = rows[j][3]
            if not t2.startswith("add "):
                continue
            parts = t2[4:].split(", ")
            if len(parts) == 3 and parts[0] == rd and parts[1] == rd:
                try:
                    resolved[o] = page + int(parts[2].lstrip("#"), 16)
                except Exception:  # noqa: BLE001
                    pass
            break

    for o, va, insn, text in rows:
        extra = ""
        if o in resolved:
            s = mi.cstr(3, resolved[o])
            if s:
                extra = f'   ; {resolved[o]:#x} "{s[:52]}"'
        mark = "  <<< predicate" if o == pred_off else ""
        print(f"  {o:#08x}  {insn:08x}  {text}{extra}{mark}")

    # what does the predicate's own body do?
    print(f"\n#  predicate body (first 24 instructions from {PRED_VA:#x})")
    for i in range(24):
        o = pred_off + i * 4
        insn = struct.unpack_from("<I", img, o)[0]
        va = mi.off_to_va(3, o)
        print(f"  {o:#08x}  {insn:08x}  {decode(insn, va or 0)}")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  The caller test is unambiguous: w0 == 1 means locked, anything else")
    print("  means writable. So the question reduces to what makes this predicate")
    print("  return 1.")
    print()
    print("  Two candidate sources, and they behave very differently:")
    print("   - a fuse / hardware security state -> fixed for the life of the SoC")
    print("   - a field read from storage        -> was set by something, and in")
    print("                                          principle can be unset")
    print()
    print("  If the predicate loads from a structure pointer it was passed, it is")
    print("  reading state from an object (storage/config), not from a register.")
    print("  That would place it in the second category, which matters a great deal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
