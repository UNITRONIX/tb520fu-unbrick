#!/usr/bin/env python3
"""
analyze_melf_map.py - map the data regions of a melf and compare its embedded
Firehose image with a standalone programmer ELF.

What this answers
-----------------
1. Where does the real data end, and how much trailing padding is there?
   (Sahara never requests the padding, which is why the transferred byte count is
   always less than the file size.)
2. Is the standalone `prog_firehose_ddr.elf` the same code as one of the inner
   images? On TB520FU the answer is yes, bit for bit - which is why signing that
   standalone file could never have helped.

Usage
-----
  python analyze_melf_map.py --melf path/to/xbl_s_devprg_ns.melf
  python analyze_melf_map.py --melf ... --standalone path/to/prog_firehose_ddr.elf
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"


def elf_headers(data: bytes) -> list[dict]:
    """Collect every plausible inner ELF header with its class/machine/entry."""
    out = []
    i = 0
    while True:
        i = data.find(ELF_MAGIC, i)
        if i < 0:
            break
        if i + 20 <= len(data) and data[i + 4] in (1, 2):
            cls = data[i + 4]
            machine = struct.unpack_from("<H", data, i + 18)[0]
            if cls == 1:
                entry = struct.unpack_from("<I", data, i + 24)[0]
                phnum = struct.unpack_from("<H", data, i + 44)[0]
            else:
                entry = struct.unpack_from("<Q", data, i + 24)[0]
                phnum = struct.unpack_from("<H", data, i + 56)[0]
            out.append(dict(off=i, cls=cls, machine=machine,
                            entry=entry, phnum=phnum))
        i += 4
    return out


def data_clusters(data: bytes, start: int, gap: int = 4096,
                  min_len: int = 1024) -> list[tuple[int, int, int]]:
    """Cluster the non-padding bytes of the blob into readable segments.

    Firmware is full of embedded strings and tables separated by short runs of
    padding, so reporting every contiguous non-00/non-FF run produces hundreds of
    meaningless two-digit entries. What is actually informative is where the file's
    real content ends and how much padding follows.

    Runs separated by less than `gap` bytes of padding are merged. Returns
    (start, end, populated_bytes) triples for clusters with real content.
    """
    runs = []
    in_run = False
    run_start = 0
    for i in range(start, len(data)):
        is_data = data[i] not in (0x00, 0xFF)
        if is_data and not in_run:
            in_run = True
            run_start = i
        elif not is_data and in_run:
            in_run = False
            runs.append((run_start, i))
    if in_run:
        runs.append((run_start, len(data)))

    if not runs:
        return []

    clusters: list[tuple[int, int, int]] = []
    c_start, c_end = runs[0]
    populated = c_end - c_start
    for rs, re_ in runs[1:]:
        if rs - c_end <= gap:
            c_end = re_
            populated += re_ - rs
        else:
            clusters.append((c_start, c_end, populated))
            c_start, c_end = rs, re_
            populated = re_ - rs
    clusters.append((c_start, c_end, populated))

    return [c for c in clusters if (c[1] - c[0]) >= min_len]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Map melf data regions and compare embedded vs standalone "
                    "Firehose.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--melf", required=True, type=Path)
    ap.add_argument("--standalone", type=Path, default=None,
                    help="optional standalone programmer ELF to compare against")
    args = ap.parse_args(argv)

    if not args.melf.is_file():
        print(f"ERROR: no such file: {args.melf}")
        return 2

    d = args.melf.read_bytes()
    print(f"melf : {args.melf.name}")
    print(f"size : {len(d)} B")
    print()

    # ---- 1. data clusters ------------------------------------------------
    headers = elf_headers(d)
    blob_start = headers[1]["off"] if len(headers) > 1 else 0x1300
    clusters = data_clusters(d, blob_start)

    print("=== CONTENT CLUSTERS (runs of real data, gaps under 4 KB merged) ===")
    print("  start       end         span        populated")
    for a, b, pop in clusters:
        pct = 100.0 * pop / (b - a)
        print(f"  0x{a:07X}..0x{b:07X}  {b - a:>9} B  {pop:>9} B ({pct:.0f}%)")
    print()

    # ---- 2. trailing padding --------------------------------------------
    if clusters:
        last_end = clusters[-1][1]
        print("=== TRAILING PADDING ===")
        print(f"  last content cluster ends at 0x{last_end:X} ({last_end})")
        print(f"  file is {len(d)} B -> padding {len(d) - last_end} B")
        print(f"  bytes after it: {d[last_end:last_end + 8].hex()}")
        print()
        print("  Sahara requests images, not the file, so this padding is never")
        print("  transferred. A transfer of (file size - padding) bytes is")
        print("  complete, not truncated.")
        print()

    # ---- 3. images -------------------------------------------------------
    print("=== IMAGES ===")
    for idx, h in enumerate(headers):
        end = headers[idx + 1]["off"] if idx + 1 < len(headers) else len(d)
        img = d[h["off"]:end]
        ff_tail = len(img) - len(img.rstrip(b"\xff"))
        cls = "ELF32" if h["cls"] == 1 else "ELF64"
        print(f"  [{idx}] @0x{h['off']:07X}  {cls}  machine=0x{h['machine']:02X}  "
              f"entry=0x{h['entry']:X}  phnum={h['phnum']}  "
              f"size={end - h['off']}  trailing_FF={ff_tail}")
    print()

    # ---- 4. comparison ---------------------------------------------------
    if args.standalone is not None:
        if not args.standalone.is_file():
            print(f"ERROR: no such file: {args.standalone}")
            return 2
        fh = args.standalone.read_bytes()
        print("=== STANDALONE FIRMWARE COMPARISON ===")
        print(f"  standalone: {args.standalone.name}  {len(fh)} B")
        matched = False
        for idx, h in enumerate(headers):
            end = headers[idx + 1]["off"] if idx + 1 < len(headers) else len(d)
            img = d[h["off"]:end]
            if img[:len(fh)] == fh:
                matched = True
                print(f"  image [{idx}] @0x{h['off']:X} CONTAINS the standalone file "
                      f"({len(fh)} B)")
                extra = len(img) - len(fh)
                if extra > 0:
                    print(f"       image is {len(img)} B, so {extra} B of padding follow")
                    print(f"       first padding bytes: {img[len(fh):len(fh) + 8].hex()}")
                print()
                print("  -> The standalone file is the SAME CODE, in the wrong")
                print("     container. Rejecting it says nothing about the code.")
                break
        if not matched:
            print("  no inner image starts with the standalone file's bytes")
            # A near match is still informative
            for idx, h in enumerate(headers):
                end = headers[idx + 1]["off"] if idx + 1 < len(headers) else len(d)
                img = d[h["off"]:end]
                if len(img) == len(fh):
                    same = sum(1 for x, y in zip(img, fh) if x == y)
                    print(f"  image [{idx}] has the same size; "
                          f"{same}/{len(fh)} bytes identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
