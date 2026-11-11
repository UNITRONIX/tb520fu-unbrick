#!/usr/bin/env python3
"""ddr_windows_analysis.py - what is in the two windows that hold real data?

The discovery
-------------
Sampling all eight dumped DDR windows at 4 MiB resolution shows exactly two contain
anything the machine wrote:

    DDRCS0_0   0x80000000   real content 0x80000000 .. 0x81c00000   (28 MiB)
    DDRCS1_0   0x880000000  real content 0x8af800000 .. 0x8bfc00000 (~275 MiB)
    the other six windows   entirely 0xFF

So the earlier framing - "DDR stops at 40 MiB" - was wrong in an important way. Six
windows are unmapped, but the second one carries substantial content near its top end.

This script examines what that content actually is: code, data, or strings. The address is
unusual - `0x8bc000000` is high in CS1 - which suggests a relocated or shared region rather
than low-memory boot code.

Read-only, offline.

Usage
    python ddr_windows_analysis.py
    python ddr_windows_analysis.py --dir <path>
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

DEFAULT_DIR = Path(r"C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\com_attempt")

TARGETS = [
    ("DDRCS1_0", 0x880000000, 0x8AF800000, 0x8BFC00000),
    ("DDRCS0_0", 0x80000000, 0x80000000, 0x81C00000),
]

MARKERS = [
    b"XBL", b"SBL", b"ABL", b"UEFI", b"uefi", b"Firehose", b"firehose",
    b"lapis", b"LANAI", b"pineapple", b"sahara", b"Sahara",
    b"boot_", b"DDR", b"ddr", b"training", b"Training",
    b"qcom", b"Qualcomm", b"panel", b"Panel", b"display",
    b"USB", b"usb", b"PMIC", b"pmic", b"charger", b"charger",
]


def find(directory: Path, name: str) -> Path | None:
    for c in (directory / f"{name}.BIN", directory / f".{name}.BIN"):
        if c.is_file():
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    args = ap.parse_args()
    d = Path(args.dir)

    for name, base, lo, hi in TARGETS:
        f = find(d, name)
        if f is None:
            print(f"\n{name}: no file")
            continue

        off_lo = lo - base
        off_hi = hi - base
        size = f.stat().st_size
        off_hi = min(off_hi, size)

        print("=" * 78)
        print(f"#  {name}   content {lo:#x} .. {hi:#x}   ({(off_hi-off_lo)/(1<<20):.0f} MiB)")
        print("=" * 78)

        with f.open("rb") as fh:
            fh.seek(off_lo)
            blob = fh.read(off_hi - off_lo)

        print(f"  read {len(blob)} bytes")

        nz = sum(1 for b in blob if b not in (0, 0xFF))
        print(f"  meaningful bytes: {nz}/{len(blob)} ({nz/len(blob)*100:.1f}%)")

        # head
        print("\n  first 128 bytes:")
        for i in range(0, min(128, len(blob)), 16):
            words = " ".join(f"{struct.unpack_from('<I', blob, i + k)[0]:08x}"
                             for k in range(0, 16, 4))
            txt = "".join(chr(c) if 32 <= c < 127 else "." for c in blob[i:i + 16])
            print(f"    {lo + i:#012x}  {words}  |{txt}|")

        # is it ARM64?
        words = struct.unpack_from(f"<{min(len(blob), 65536)//4}I", blob, 0)
        plausible = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
        print(f"\n  ARM64-plausible instruction ratio (first 64 KiB): "
              f"{plausible/max(1,len(words)):.0%}")

        # markers
        print("\n  markers:")
        any_hit = False
        for m in MARKERS:
            hits = []
            start = 0
            while True:
                k = blob.find(m, start)
                if k < 0 or len(hits) >= 3:
                    break
                hits.append(k)
                start = k + 1
            if hits:
                any_hit = True
                print(f"    {m.decode():<12} " +
                      ", ".join(f"{lo + h:#x}" for h in hits))
        if not any_hit:
            print("    none of the known markers appear")

        # longest printable runs
        print("\n  longest printable runs:")
        runs = []
        for mm in re.finditer(rb"[\x20-\x7e]{20,}", blob):
            s = mm.group()
            alpha = sum(1 for c in s if chr(c).isalpha() or c in b" _:=-%.,()/[]")
            if alpha / len(s) > 0.85:
                runs.append((mm.start(), s.decode("ascii", "replace")))
        runs.sort(key=lambda r: -len(r[1]))
        for off, s in runs[:15]:
            print(f"    {lo + off:#012x}  {s[:96]}")

        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
