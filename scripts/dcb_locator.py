#!/usr/bin/env python3
"""dcb_locator.py - find where the DCB and pre-DDR DTB are loaded from.

The mechanism
-------------
shrm_probe.py extracted image [4] of the melf and found it references, by name:

    /A00C_8_0200_1_dcb.bin
    /A00C_8_0100_1_dcb.bin
    pre-ddr-lanai-1.0.dtb

These are not compiled-in blobs - they are file names resolved at runtime, from a
filesystem image on UFS (the modem/boot filesystem). The devprg's own strings
agree:

    sbl1_load_ddr_training_data
    boot_pre_ddr_dtb_load
    CDT not found in any storage media, using defaults

So DDR bring-up in EDL reads storage: a DCB (DDR configuration block) naming the
memory part, and a DTB describing the board's DDR topology. If either lookup
fails, training cannot be parameterised correctly.

This script does two things:

  1. searches every readable artefact we already have on disk for those exact
     filenames, to learn whether the payloads are inside images we hold;
  2. reports which of our local files could contain them, so the DCB can be
     validated offline instead of guessed at.

Read-only, offline.

Usage
    python dcb_locator.py
    python dcb_locator.py --root C:\\ProgramData\\RSA\\Download\\RomFiles
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

NAMES = [
    b"A00C_8_0200_1_dcb.bin",
    b"A00C_8_0100_1_dcb.bin",
    b"pre-ddr-lanai-1.0.dtb",
    b"lanai-1.0",
    b"dcb.bin",
    b"pre-ddr",
]

#: Files big enough to be a filesystem/payload image, worth scanning.
SCAN_SUFFIXES = {".bin", ".img", ".mbn", ".elf", ".melf", ".hex", ".x"}


def scan(path: Path, limit: int) -> list[tuple[bytes, int]]:
    hits = []
    try:
        size = path.stat().st_size
    except OSError:
        return hits
    if size > limit:
        return hits
    try:
        data = path.read_bytes()
    except OSError:
        return hits
    for n in NAMES:
        i = data.find(n)
        if i >= 0:
            hits.append((n, i))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"C:\ProgramData\RSA\Download\RomFiles")
    ap.add_argument("--extra", default=r"C:\Users\UNITRONIX\Downloads")
    ap.add_argument("--limit", type=int, default=600 << 20,
                    help="skip files larger than this")
    args = ap.parse_args()

    roots = [Path(args.root), Path(args.extra)]
    print("=" * 78)
    print("#  hunting for the DCB / pre-DDR DTB by name")
    print("=" * 78)
    for r in roots:
        print(f"  root: {r}  exists={r.is_dir()}")

    total = 0
    for r in roots:
        if not r.is_dir():
            continue
        print(f"\n#  scanning {r}")
        for p in r.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in SCAN_SUFFIXES:
                continue
            hits = scan(p, args.limit)
            for name, off in hits:
                total += 1
                print(f"  FOUND {name.decode():<26} @ {off:#x} in {p}")
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                # show what follows the name - a filesystem entry has metadata
                seg = data[off:off + 96]
                print(f"        ctx: {seg[:64]!r}")

    print()
    print("=" * 78)
    print("#  RESULT")
    print("=" * 78)
    if total:
        print(f"  {total} hit(s). The DCB / DTB payloads exist in files we hold.")
        print("  Next: extract them and compare against the board - a DCB naming")
        print("  the wrong memory part is a concrete cause for failed training.")
    else:
        print("  No hits. The names appear only in the devprg as strings, which")
        print("  means the files live inside a UFS filesystem image (modem/boot),")
        print("  not in any standalone blob we have. Consequence: the DCB cannot")
        print("  be inspected offline from these packages alone - it would have to")
        print("  be read from the device, or obtained from a matching unit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
