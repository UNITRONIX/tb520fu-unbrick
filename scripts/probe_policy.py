#!/usr/bin/env python3
"""probe_policy.py - read the debug-policy and charger properties in full.

Why
---
compare_firmware.py showed the DDR parameters are byte-identical across 17.5 and
18.5, so they are not the cause. That moves attention to two things the same
comparison surfaced:

  /sw/pmic/pm/charger:min-dbg-board-id = 3000
  /sw/pmic/pm/charger:max-dbg-board-id = 11000

A debug-policy board-id *range* living under the charger node is odd placement, and
a range is a condition rather than a constant. The boot path has
"debug policy applied" / "no debug policy applied" strings, so this range is almost
certainly what decides whether a policy is accepted.

This dumps the whole charger subtree and every property whose name suggests policy,
so the shape of the decision is visible.

Read-only, offline.

Usage
    python probe_policy.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decode_fdt import Fdt  # noqa: E402

DCB = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_config.elf")

INTEREST = ("dbg", "debug", "policy", "board", "bd", "charger", "vbat",
            "vsys", "dbc", "pon")


def dcb_blob() -> bytes:
    """Find the payload whose first four bytes are an FDT magic.

    The name table in xbl_config.elf has more than one entry per payload (the same
    DCB is listed under both its full name and `dcb.bin`), and the (offset, length)
    pair that follows a name is relative to 0x200 - but not every pair leads to the
    tree. Naively taking the first pair after the first name yields 0x4346474c
    ("CFGL"), which is a different structure entirely.

    So: try every candidate offset in the neighbourhood of the name and accept the
    first whose magic is d00dfeed and whose header is self-consistent.
    """
    d = DCB.read_bytes()
    n = d.find(b"A00C_8_0200_1_dcb.bin")
    if n < 0:
        raise RuntimeError("DCB name not found")

    FDT_MAGIC = b"\xd0\x0d\xfe\xed"
    for probe in range(n + len(b"A00C_8_0200_1_dcb.bin"),
                       min(n + 96, len(d) - 8)):
        off, ln = struct.unpack_from("<II", d, probe)
        if not (0 < off < len(d)):
            continue
        real = off + 0x200
        if real + 8 > len(d):
            continue
        if d[real:real + 4] != FDT_MAGIC:
            continue
        total = struct.unpack_from(">I", d, real + 4)[0]
        if not (1000 < total <= len(d) - real + 16):
            continue
        return d[real:real + min(ln, total)]
    raise RuntimeError("no FDT-magic payload found near the DCB name")


def show(value: bytes) -> str:
    if not value:
        return "<empty>"
    if all(32 <= c < 127 or c == 0 for c in value) and value[-1] == 0:
        return repr(value.split(b"\x00")[0].decode("ascii", "replace"))
    if len(value) in (1, 2, 4, 8):
        return f"{int.from_bytes(value, 'big')} (0x{int.from_bytes(value, 'big'):x})"
    return value.hex(" ")


def main() -> int:
    f = Fdt(dcb_blob())
    props = list(f.walk())

    print("=" * 78)
    print("#  the charger subtree in full")
    print("=" * 78)
    for p, n, v in props:
        if p.startswith("sw/pmic/pm/charger"):
            print(f"  /{p}:{n} = {show(v)}")

    print()
    print("=" * 78)
    print("#  every policy / debug / battery property")
    print("=" * 78)
    seen = set()
    for p, n, v in props:
        low = (p + "/" + n).lower()
        if not any(k in low for k in INTEREST):
            continue
        key = (p, n)
        if key in seen:
            continue
        seen.add(key)
        print(f"  /{p}:{n} = {show(v)}")

    print()
    print("=" * 78)
    print("#  nodes that look like they govern boot policy")
    print("=" * 78)
    nodes = sorted({p for p, _, _ in props})
    for nd in nodes:
        if any(k in nd.lower() for k in ("boot", "policy", "charger", "pmic/pm")):
            print(f"  /{nd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
