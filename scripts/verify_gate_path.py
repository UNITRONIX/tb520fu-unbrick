#!/usr/bin/env python3
"""verify_gate_path.py - confirm which function actually returns the lock state.

A mistake to avoid
------------------
Reading code around a `bl` and assuming the callee is what you want is how wrong
conclusions get made. The gate site is:

    0x149a0e98  mov x0, x21
    0x149a0e9c  mov x1, x19
    0x149a0ea0  bl 0x149a369c
    0x149a0ea4  cmp w0, #0x1
    0x149a0ea8  b.ne 0x149a0f30      non-1 -> allowed
    0x149a0eac  "device is locked, cannot write"

So the value compared against 1 comes from 0x149a369c, with two arguments. That
makes 0x149a369c a predicate taking (something, something) - not a global state
getter. Its return value of **1 specifically** means locked.

The useful question is therefore: what does 0x149a369c test? It returns 1 for
"locked" and something else otherwise. Reading its body shows the condition - and
that condition is what decides whether this tablet can be written.

This script disassembles it from its true entry and resolves its strings.

Read-only, offline.

Usage
    python verify_gate_path.py
    python verify_gate_path.py --func 0x369c --count 90
"""
from __future__ import annotations

import argparse
import struct

from image_dump import MelfImages
from a64 import decode
from find_func_start import is_prologue, is_terminal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=None)
    ap.add_argument("--image", type=int, default=3)
    ap.add_argument("--func", type=lambda x: int(x, 0), default=0x369C)
    ap.add_argument("--count", type=int, default=90)
    args = ap.parse_args()

    mi = MelfImages(args.melf) if args.melf else MelfImages()
    img = mi.image(args.image)

    # find the entry at or before the address
    entry = None
    off = args.func & ~3
    while off > 0x1000:
        insn = struct.unpack_from("<I", img, off)[0]
        if is_prologue(insn):
            prev = struct.unpack_from("<I", img, off - 4)[0]
            if is_terminal(prev):
                entry = off
                break
        off -= 4
    if entry is None:
        print("no prologue found")
        return 1

    print("=" * 78)
    print(f"#  function containing image+{args.func:#x}  (entry image+{entry:#x})")
    print("=" * 78)

    # resolve adrp+add string constants across the function
    rows = []
    for i in range(args.count):
        o = entry + i * 4
        if o + 4 > len(img):
            break
        insn = struct.unpack_from("<I", img, o)[0]
        va = mi.off_to_va(args.image, o)
        rows.append((o, va, insn, decode(insn, va if va is not None else o)))

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
                    imm = int(parts[2].lstrip("#"), 16)
                except Exception:  # noqa: BLE001
                    break
                resolved[o] = page + imm
            break

    for o, va, insn, text in rows:
        extra = ""
        if o in resolved:
            s = mi.cstr(args.image, resolved[o])
            if s:
                extra = f'   ; {resolved[o]:#x} "{s[:56]}"'
        va_s = f"{va:#012x}" if va is not None else "------------"
        print(f"  {o:#08x}  {va_s}  {insn:08x}  {text}{extra}")

    print("\n" + "=" * 78)
    print("#  how to read the answer")
    print("=" * 78)
    print("  Look for the comparison that produces the returned 1. The caller does")
    print("  'cmp w0, #1 / b.ne allow', so this function returns 1 exactly when the")
    print("  device is locked. Whatever it loads before returning 1 is the source of")
    print("  truth - a fuse read, a partition field, or a policy value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
