#!/usr/bin/env python3
"""map_ddr_dumps.py - what is actually in the dumped DDR windows?

The dumps came from QSaharaServer in memory-debug mode. Every file it wrote has a leading
dot when a previous copy existed (`.DDRCS0_0.BIN`), which is easy to miss.

This walks each window and reports where real content is, page by page, so the shape of
the memory map is measured rather than assumed.

The question it answers: is CS0 truncated at 40 MiB, or does it contain data further out
that the crash handler simply refused to serve in the earlier probes?

Read-only, offline.

Usage
    python map_ddr_dumps.py
    python map_ddr_dumps.py --dir <path> --page 65536
"""
from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent / "com_attempt"

WINDOWS = [
    ("DDRCS0_0", 0x80000000),
    ("DDRCS1_0", 0x880000000),
    ("DDRCS1_1", 0x900000000),
    ("DDRCS1_2", 0x980000000),
    ("DDRCS2_0", 0xA00000000),
    ("DDRCS2_1", 0xA80000000),
    ("DDRCS2_2", 0xB00000000),
    ("DDRCS2_3", 0xB80000000),
]


def find_file(directory: Path, name: str) -> Path | None:
    """QSaharaServer prefixes a dot when the target file already exists."""
    for cand in (directory / f"{name}.BIN", directory / f".{name}.BIN",
                 directory / f"{name}.bin", directory / f".{name}.bin"):
        if cand.is_file():
            return cand
    return None


def classify(page: bytes) -> str:
    if not page:
        return "empty"
    if all(b == 0xFF for b in page):
        return "FF"
    if all(b == 0x00 for b in page):
        return "zero"
    # ASCII 'W' fill (memory test pattern)
    if page.count(0x57) > len(page) * 0.9:
        return "W-fill"
    nz = sum(1 for b in page if b)
    if nz < len(page) * 0.1:
        return "sparse"
    return "real"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--page", type=int, default=1 << 20, help="page size to sample")
    ap.add_argument("--maxpages", type=int, default=64, help="pages to sample per window")
    args = ap.parse_args()

    d = Path(args.dir)
    print("=" * 78)
    print(f"#  DDR dump map   {d}")
    print("=" * 78)

    for name, base in WINDOWS:
        f = find_file(d, name)
        if f is None:
            print(f"\n{name:<10}  (no file)")
            continue

        size = f.stat().st_size
        print(f"\n{name:<10}  {size/(1<<20):>7.0f} MiB   file={f.name}")

        if size == 0:
            print("           empty file")
            continue

        with f.open("rb") as fh:
            # sample up to maxpages across the whole file
            step = max(args.page, size // max(1, args.maxpages))
            step = (step // 4096) * 4096 or 4096
            results = []
            off = 0
            while off < size:
                fh.seek(off)
                page = fh.read(min(step, 4096))
                results.append((off, classify(page)))
                off += step

        # summarise runs
        counts: dict[str, int] = {}
        for _, k in results:
            counts[k] = counts.get(k, 0) + 1

        real = [o for o, k in results if k == "real"]
        print(f"           sampled {len(results)} offsets"
              f"   real={counts.get('real',0)}"
              f"  FF={counts.get('FF',0)}"
              f"  zero={counts.get('zero',0)}"
              f"  W-fill={counts.get('W-fill',0)}"
              f"  sparse={counts.get('sparse',0)}")

        if real:
            lo = min(real)
            hi = max(real)
            print(f"           real content from {base + lo:#x} to {base + hi:#x}")
            print(f"           ({(hi - lo) / (1<<20):.0f} MiB span)")
        else:
            print(f"           no real content found in the sample")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  W-fill is the ASCII letter 'W' repeated - a memory test pattern.")
    print("  FF is unmapped. zero is cleared or uninitialised-but-addressable.")
    print("  Only 'real' pages hold anything the machine actually wrote.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
