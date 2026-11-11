"""fedl_latch.py - read the FEDL condition from a boot log, and explain what it means.

Why this exists
---------------
`docs/39` and `docs/41` reduced the hardware route to a single masked comparison, but left
the result unobservable: the decision reads a register in an always-on block that no crash
handler maps.

It is observable after all, through a side door. XBL's own boot log prints that register:

    S - Boot Config @ 0x221c8600 = 0x00000001

and the decision function (`0x148818cc`) is:

    ldrh w8, [0x221C8600]
    and  w8, w8, #0x3e        bits 1..5
    cmp  w8, #0x6             must equal 0b000110
    csel w0, wzr, wzr, eq

So the FEDL condition is `(BootConfig >> 1) & 0x1F == 6`, and every boot log answers it
directly. That converts "hold D+ low and hope" into a number that can be read before and
after an attempt.

The value in the captures on disk is 0x1 - bits 1..5 are zero - so on every boot recorded
here, the condition was **false**. That is consistent with the fact that no short was ever
applied, and it is the baseline the next attempt has to change.

What a positive result would look like
--------------------------------------
A log whose `Boot Config` has bits 1..5 == 6, i.e. values with 0x0C set in that field:
0x0D, 0x2D, 0x4D, ... (bit 0 is the `Secure Boot: On` marker and bit 6+ are unrelated).
Finding one would prove the D+ short latched, whether or not 9008 appeared - which makes
the physical attempt diagnosable even when it fails.

Usage
    python fedl_latch.py                       # scan known captures
    python fedl_latch.py --dump <file>
    python fedl_latch.py --value 0x0D          # test a value
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

BOOT_CONFIG = re.compile(rb"Boot Config @ 0x221c8600 = (0x[0-9a-fA-F]+)")
SECURE = re.compile(rb"Secure Boot: (\w+)")


def evaluate(value: int) -> tuple[int, bool]:
    """(bits 1..5, does the FEDL condition hold)"""
    bits = (value >> 1) & 0x1F
    return bits, bits == 6


def describe(value: int) -> str:
    bits, ok = evaluate(value)
    return (f"BootConfig={value:#010x}  bits1..5={bits:#07b} ({bits})  "
            f"FEDL condition (==0b000110): {'TRUE' if ok else 'false'}")


def scan(path: Path) -> tuple[int, bool] | None:
    if not path.is_file():
        print(f"  missing: {path}")
        return None
    buf = path.read_bytes()
    hits = list(BOOT_CONFIG.finditer(buf))
    if not hits:
        print(f"  {path.name}: no 'Boot Config @ 0x221c8600' line")
        return None
    print(f"  {path.name}: {len(hits)} boot log(s)")
    result = None
    for m in hits:
        value = int(m.group(1), 16)
        print(f"    {describe(value)}")
        result = evaluate(value)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=None)
    ap.add_argument("--value", default=None, help="evaluate a literal value, e.g. 0x0D")
    args = ap.parse_args()

    print("=" * 76)
    print("#  FEDL latch: the condition is (BootConfig @ 0x221C8600 >> 1) & 0x1F == 6")
    print("=" * 76)

    if args.value:
        v = int(args.value, 16) if args.value.lower().startswith("0x") else int(args.value)
        print(f"  {describe(v)}")
        return 0 if evaluate(v)[1] else 1

    targets = ([Path(args.dump)] if args.dump else [
        REPO / "com_attempt" / "DDRCS0_0_first40MB.bin",
        REPO / "com_attempt" / "real_content" / "DDRCS0_0_first28MB.bin",
    ])

    seen_any = False
    positive = False
    for p in targets:
        r = scan(p)
        if r is not None:
            seen_any = True
            positive = positive or r[1]
        print()

    if not seen_any:
        print("  no boot log readable - nothing decided")
        return 2

    print()
    if positive:
        print("  *** At least one boot had the FEDL condition TRUE. ***")
        print("      The D+ short latched. If that boot did not offer 9008, the blocker")
        print("      is downstream of the latch and docs/41 s3 needs re-reading.")
        return 0
    print("  Every recorded boot has the FEDL condition FALSE - so no recorded boot had")
    print("  a D+ short applied. That is the baseline, not a failure: the short has never")
    print("  been tried. After an attempt, re-run this on a fresh capture: a TRUE here")
    print("  proves the short was seen even if 9008 did not appear.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
