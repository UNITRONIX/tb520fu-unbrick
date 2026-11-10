#!/usr/bin/env python3
"""capability_inventory.py - enumerate every escalation-relevant surface we hold.

Purpose
-------
Rather than pursue one hypothesis, inventory the artefacts for anything that could
constitute a path: a debug interface, an alternate download mode, a memory-write
primitive, an auth bypass, or a code path that skips a check.

Everything here is read-only and offline. The output is a map, not an exploit.

What counts as a "path"
-----------------------
  EDL      ways to reach PBL EDL or an equivalent download mode
  DEBUG    JTAG / EUD / DCC / debug-policy / test interfaces
  WRITE    primitives that mutate memory or storage
  BYPASS   conditional checks whose failure is fail-open
  AUTH     signing / hash / VIP gates and what happens when they are absent

Usage
    python capability_inventory.py
    python capability_inventory.py --grep 0x1FD9000
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from image_dump import MelfImages

#: (label, image number, terms). Terms are searched case-insensitively in strings.
CATEGORIES: list[tuple[str, list[str]]] = [
    ("EDL / download-mode entry", [
        "EDL", "emergency", "dload", "download mode", "PBL EDL",
        "sahara", "firehose", "crashdump", "9008", "900e",
    ]),
    ("DEBUG / test interfaces", [
        "JTAG", "jtag", "EUD", "eud", "DCC", "dbg", "DBG", "debug",
        "test point", "testpoint", "trace", "ETM", "coresight",
        "boot_dbginfo", "dbginfo", "debug policy", "DebugPolicy",
    ]),
    ("WRITE primitives", [
        "poke", "patch", "program", "erase", "write", "memcpy",
        "flash", "burn",
    ]),
    ("BYPASS / fail-open conditions", [
        "skip", "Skip", "bypass", "Bypass", "override", "ignore",
        "not allowed", "disabled", "unlocked", "not locked",
    ]),
    ("AUTH / integrity gates", [
        "VIP", "auth", "Auth", "signature", "Signature", "hash",
        "cert", "secure boot", "Secure Boot", "SMC", "qsee", "QSEE",
        "tzbsp", "TZBSP", "hrot", "root of trust",
    ]),
    ("Storage / partition plumbing", [
        "lenovolock", "lenovocust", "lenovoraw", "GPT", "gpt",
        "physical_partition", "LUN", "lun", "UFS", "ufs",
    ]),
]


def strings_with(img: bytes, term: str, minlen: int = 6):
    """Yield (offset, string) for text runs containing term."""
    t = term.encode()
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, img):
        s = m.group()
        if t in s:
            txt = s.decode("ascii", "replace")
            alpha = sum(c.isalpha() or c in " _:=-%.,()/[]<>+*" for c in txt) / len(txt)
            if alpha > 0.72:
                yield m.start(), txt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", default=None, help="search one literal term instead")
    ap.add_argument("--max", type=int, default=14, help="max hits shown per term")
    args = ap.parse_args()

    mi = MelfImages()
    names = {1: "img1 vendor blob", 2: "XBL core", 3: "Firehose", 4: "DDR/shrm"}

    if args.grep:
        print("=" * 78)
        print(f"#  literal search: {args.grep!r}")
        print("=" * 78)
        for n in (2, 3, 4):
            img = mi.image(n)
            hits = list(strings_with(img, args.grep, 4))
            print(f"\n  image [{n}] {names[n]}: {len(hits)} hit(s)")
            for off, s in hits[:40]:
                va = mi.off_to_va(n, off)
                print(f"    {va if va else off:#012x}  {s[:104]}")
        return 0

    print("=" * 78)
    print("#  capability inventory across the melf's inner images")
    print("=" * 78)

    totals: dict[str, int] = {}
    for label, terms in CATEGORIES:
        print("\n" + "=" * 78)
        print(f"#  {label}")
        print("=" * 78)
        cat_total = 0
        for term in terms:
            found_any = False
            for n in (2, 3, 4):
                img = mi.image(n)
                hits = list(strings_with(img, term))
                if not hits:
                    continue
                if not found_any:
                    print(f"\n  [{term}]")
                    found_any = True
                for off, s in hits[:args.max]:
                    va = mi.off_to_va(n, off)
                    where = f"{va:#012x}" if va else f"off {off:#08x}"
                    print(f"    img{n} {where}  {s[:96]}")
                cat_total += len(hits)
                if len(hits) > args.max:
                    print(f"    img{n} ... {len(hits) - args.max} more")
            if not found_any:
                pass
        if cat_total == 0:
            print("  (nothing found)")
        totals[label] = cat_total

    print("\n" + "=" * 78)
    print("#  SUMMARY BY CATEGORY")
    print("=" * 78)
    for label, n in totals.items():
        print(f"  {label:<34} {n:>5} matching strings")

    print("\n" + "=" * 78)
    print("#  HOW TO USE THIS")
    print("=" * 78)
    print("  A hit is a lead, not a capability. Each one has to be traced to the")
    print("  branch that acts on it before it means anything - the write-gate work")
    print("  (docs/17-write-gate.md) is the template: name -> reference site ->")
    print("  decoded condition -> what happens on each outcome.")
    print()
    print("  The categories are ordered by what would actually help:")
    print("    EDL     a download path that does not need the failing programmer")
    print("    DEBUG   an interface that bypasses the XML listener entirely")
    print("    WRITE   a primitive that is not gated by lenovolock")
    print("    BYPASS  a condition whose failure grants permission")
    print("    AUTH    what precisely is verified, and what is not")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
