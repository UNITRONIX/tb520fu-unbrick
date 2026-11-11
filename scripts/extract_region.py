#!/usr/bin/env python3
"""extract_region.py - cut a byte range out of a large dump without loading it all.

PowerShell's byte[] cannot hold the 260 MB slice without an OutOfMemoryException, so this
does the same job with a chunked copy.

Usage
    python extract_region.py --file DDRCS1_0.BIN --base 0x880000000 \
        --from 0x8af800000 --to 0x8bfc00000 --out content.bin
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--base", type=lambda x: int(x, 0), required=True,
                    help="address of byte 0 of the file")
    ap.add_argument("--from", dest="start", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--to", dest="end", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.file)
    dst = Path(args.out)
    if not src.is_file():
        print(f"missing {src}")
        return 2

    off = args.start - args.base
    length = args.end - args.start
    if off < 0:
        print("start precedes the file base")
        return 2

    size = src.stat().st_size
    if off + length > size:
        length = size - off
        print(f"clamped length to {length} (file is {size} bytes)")

    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fh, dst.open("wb") as out:
        fh.seek(off)
        remaining = length
        chunk = 8 << 20
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            out.write(data)
            remaining -= len(data)

    written = dst.stat().st_size
    print(f"wrote {dst}  {written} bytes ({written/(1<<20):.1f} MiB)")
    print(f"source range {args.start:#x} .. {args.start + written - 1:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
