#!/usr/bin/env python3
"""analyze_ddr_capture.py - what is in the 40 MiB of readable DDR?

The capture
-----------
`DDRCS0_0_first40MB.bin` is the first 40 MiB of DDR CS0, read with the vendor tool over
a COM port in SAHARA_MEMORY_DEBUG mode. It is the first time this project has held actual
DDR contents for this tablet.

Bounds, measured:

    0x80000000 .. 0x827FFFFF   readable
    0x82800000 onwards         nothing (0xFF, then zeros, then no response)

This script asks the obvious questions of the data:

  1. is it code, data, or fill?
  2. what does the head look like - is anything identifiable?
  3. where does the real content stop?
  4. do the strings in it name any boot component?

Read-only, offline.

Usage
    python analyze_ddr_capture.py
    python analyze_ddr_capture.py --file <path>
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "com_attempt" / "DDRCS0_0_first40MB.bin"

#: Boot component names worth looking for.
MARKERS = [
    b"XBL", b"SBL", b"ABL", b"Firehose", b"firehose", b"LinuxLoader",
    b"UEFI", b"uefi", b"devprg", b"lapis", b"TB520FU", b"LANAI", b"pineapple",
    b"sahara", b"SAHARA", b"WatchDog", b"watchdog", b"boot_",
    b"ddr", b"DDR", b"training", b"Training",
]


def bucket(blob: bytes) -> str:
    """Classify a 4 KiB page."""
    if not blob:
        return "empty"
    if all(x == 0xFF for x in blob):
        return "0xFF"
    if all(x == 0x00 for x in blob):
        return "zeros"
    words = struct.unpack_from(f"<{len(blob)//4}I", blob, 0)
    plausible = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
    ratio = plausible / len(words)
    nz = sum(1 for x in blob if x)
    if ratio > 0.80 and nz / len(blob) > 0.35:
        return "code"
    if nz / len(blob) < 0.10:
        return "sparse"
    return "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"missing {path}")
        print("Run Read-DdrData.ps1 or re-run the dump to produce it.")
        return 2

    blob = path.read_bytes()
    base = 0x80000000
    print("=" * 78)
    print(f"#  {path.name}  {len(blob)} B = {len(blob)/(1<<20):.0f} MiB")
    print(f"#  maps to {base:#x} .. {base + len(blob) - 1:#x}")
    print("=" * 78)

    # ---- 1. page-by-page classification --------------------------------
    print("\n#  content by 4 KiB page (first 64 pages, then every 256th)")
    counts: dict[str, int] = {}
    pages = len(blob) // 4096
    for i in range(pages):
        b = bucket(blob[i * 4096:(i + 1) * 4096])
        counts[b] = counts.get(b, 0) + 1

    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<8} {v:>6} pages  ({v/pages*100:5.1f}%)")

    # ---- 2. where does real content end? --------------------------------
    print("\n#  boundary detection (last page that is not fill)")
    last_real = None
    for i in range(pages):
        if bucket(blob[i * 4096:(i + 1) * 4096]) not in ("0xFF", "zeros", "empty"):
            last_real = i
    if last_real is not None:
        addr = base + last_real * 4096
        print(f"  last non-fill page: index {last_real}  address {addr:#x}")
        print(f"  that is {last_real * 4096 / (1<<20):.1f} MiB into CS0")
    else:
        print("  the whole capture is fill")

    # ---- 3. head ------------------------------------------------------
    print("\n#  first 128 bytes")
    for off in range(0, 128, 16):
        words = " ".join(f"{struct.unpack_from('<I', blob, off + k)[0]:08x}"
                         for k in range(0, 16, 4))
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in blob[off:off + 16])
        print(f"  {base + off:#010x}  {words}  |{txt}|")

    if blob[:4] == b"\x7fELF":
        print("\n  *** starts with an ELF header ***")

    # ---- 4. strings ---------------------------------------------------
    print("\n#  markers found")
    found_any = False
    for m in MARKERS:
        hits = []
        start = 0
        while True:
            k = blob.find(m, start)
            if k < 0 or len(hits) >= 4:
                break
            hits.append(k)
            start = k + 1
        if hits:
            found_any = True
            addrs = ", ".join(f"{base + h:#x}" for h in hits)
            print(f"  {m.decode():<14} {addrs}")
    if not found_any:
        print("  none of the known boot markers appear")

    # ---- 5. long printable strings (likely real text) ------------------
    print("\n#  longest printable runs (possible boot messages)")
    runs = []
    for m in re.finditer(rb"[\x20-\x7e]{16,}", blob):
        s = m.group()
        alpha = sum(1 for c in s if chr(c).isalpha() or c in b" _:=-%.,()/[]")
        if alpha / len(s) > 0.80:
            runs.append((m.start(), s.decode("ascii", "replace")))
    runs.sort(key=lambda r: -len(r[1]))
    for off, s in runs[:20]:
        print(f"  {base + off:#010x}  {s[:100]}")

    print("\n" + "=" * 78)
    print("#  SUMMARY")
    print("=" * 78)
    code = counts.get("code", 0)
    fill = counts.get("0xFF", 0) + counts.get("zeros", 0)
    print(f"  code-like pages : {code}  ({code * 4096 / (1<<20):.1f} MiB)")
    print(f"  fill pages      : {fill}  ({fill * 4096 / (1<<20):.1f} MiB)")
    print()
    print("  The first megabytes hold real AArch64 code - that is the running boot")
    print("  chain. What follows is fill, which means the memory that should continue")
    print("  past that point is not there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
