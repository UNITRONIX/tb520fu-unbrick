#!/usr/bin/env python3
"""decode_sbl_log.py - recover the SBL boot log from sbl_pmic_dump.bin.

What this actually is
---------------------
`docs/05-firehose-and-the-silence.md` §8 says the boot progress is only visible
over UART. Crash-dump region `sbl_pmic_dump.bin` (512 KiB @ 0x1000000000) was
assumed to be a PMIC register dump.

It is not. It contains ~500 records of 113..426 bytes each, starting at file
offset 0 and running to 0x21cd7 - the shape of a boot logger, not a register map.

The devprg's own strings name the logger:

    Format: Log Type - Time(microsec) - Message - Optional Info
    Log Type: B - Since Boot(Power On Reset),  D - Delta,  S - Statistic
    OVERFLOW
    boot_logger.c / boot_logger_ram.c

So the data should consist of text lines beginning with a log-type letter, a
timestamp in microseconds, and a message. Recovering those lines gives the boot
sequence with timings - including which stage was last before the hang.

Read-only, offline.

Usage
    python decode_sbl_log.py
    python decode_sbl_log.py --raw
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "pmic_state_probe" / "sbl_pmic_dump.bin"

#: A boot-log line looks like "B 1234567 sbl1_ddr_init, Start" or with a delta.
LINE = re.compile(rb"^([BDS])\s+(\d{1,12})\s+(.{1,160})$", re.MULTILINE)


def clusters(b: bytes, gap: int = 64) -> list[tuple[int, int]]:
    nz = [i for i, x in enumerate(b) if x]
    if not nz:
        return []
    runs, start, prev = [], nz[0], nz[0]
    for i in nz[1:]:
        if i - prev > gap:
            runs.append((start, prev))
            start = i
        prev = i
    runs.append((start, prev))
    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="also print raw first record")
    args = ap.parse_args()

    if not DATA.is_file():
        print(f"missing {DATA}")
        return 2
    b = DATA.read_bytes()

    print("=" * 78)
    print(f"#  {DATA.name}  {len(b)} B")
    print("=" * 78)

    runs = clusters(b)
    last = max(z for _, z in runs)
    print(f"  populated: 0x0..{last:#x}  ({last + 1} B), {len(runs)} clusters")

    # ---- is it text? ----------------------------------------------------
    window = b[:0x4000]
    printable = sum(1 for x in window if 32 <= x < 127 or x in (0, 9, 10, 13))
    print(f"  printable in first 16 KiB: {printable/len(window):.1%}")

    if args.raw:
        print("\n# first record, raw")
        lo, hi = runs[0]
        print(b[lo:min(hi + 1, lo + 512)].hex(" "))
        print()
        print(repr(b[lo:min(hi + 1, lo + 512)]))

    # ---- look for boot-log lines ----------------------------------------
    found = []
    for m in LINE.finditer(b):
        found.append((m.start(), m.group(1).decode(), int(m.group(2)),
                      m.group(3).decode("ascii", "replace").split("\x00")[0].strip()))
    print(f"\n# lines matching the boot-logger format: {len(found)}")
    for off, typ, t, msg in found[:60]:
        print(f"  {off:#08x}  {typ} {t:>10d}us  {msg[:100]}")

    # ---- fall back: any readable strings at all -------------------------
    if not found:
        print("\n# no formatted lines; extracting all text-like runs instead")
        text = []
        for m in re.finditer(rb"[\x20-\x7e]{10,}", b):
            s = m.group().decode("ascii", "replace")
            alpha = sum(c.isalpha() or c in " _:=-%.,()/" for c in s) / len(s)
            if alpha > 0.82:
                text.append((m.start(), s))
        print(f"  {len(text)} text-like runs")
        for off, s in text[:60]:
            print(f"  {off:#08x}  {s[:110]}")

    # ---- structure of the first few records -----------------------------
    print("\n# first 8 clusters, with their first 48 bytes as text")
    for lo, hi in runs[:8]:
        chunk = b[lo:hi + 1]
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk[:48])
        print(f"  {lo:#08x}..{hi:#08x} ({len(chunk):>4d} B) |{txt}|")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  If this is the SBL boot log, the LAST readable message names the stage")
    print("  the device reached, and its timestamp bounds the hang. That is the")
    print("  concrete answer to 'where does boot stop' - from the host, without")
    print("  opening the case.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
