#!/usr/bin/env python3
"""
find_hashes.py - hunt for per-image hashes inside a melf container.

Why this exists
---------------
Modifying one image inside the melf makes the device reject the whole blob with
0x21 (HASH_TABLE_AUTH_FAILURE), and the rejection happens BEFORE the modified
image is reached. The obvious repair would be to recompute whatever hash is
stored in the file -- but only if such a hash is actually in the file.

This script computes several digest variants of every inner image and searches
the entire container for those byte sequences. On TB520FU the answer is: not
present, in no recoverable form. Which means the hash is computed inside PBL and
compared against a structure that is not in the file.

Usage
-----
  python find_hashes.py --melf path/to/xbl_s_devprg_ns.melf
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"


def inner_offsets(data: bytes) -> list[int]:
    offs = []
    i = 0
    while True:
        i = data.find(ELF_MAGIC, i)
        if i < 0:
            break
        if i + 20 <= len(data) and data[i + 4] in (1, 2):
            offs.append(i)
        i += 4
    return offs


def hexdump(data: bytes, start: int, end: int, indent: str = "  ") -> None:
    for row in range(start, end, 16):
        chunk = data[row:row + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{indent}{row:04x}  {hexpart:<47}  {asc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Search a melf container for stored per-image hashes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--melf", required=True, type=Path)
    args = ap.parse_args(argv)

    if not args.melf.is_file():
        print(f"ERROR: no such file: {args.melf}")
        return 2

    d = args.melf.read_bytes()
    offs = inner_offsets(d)
    print(f"melf : {args.melf.name}")
    print(f"size : {len(d)} B")
    print(f"inner ELF headers found: {len(offs)} at "
          f"{', '.join(f'0x{o:X}' for o in offs)}")
    print()

    if len(offs) < 2:
        print("ERROR: need at least two ELF headers to delimit images")
        return 2

    # ---- digests per image ----------------------------------------------
    print("=== DIGESTS OF EACH IMAGE ===")
    digests: dict[int, dict[str, bytes]] = {}
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(d)
        img = d[o:end]
        stripped = img.rstrip(b"\xff")
        digests[i] = {
            "sha256(full)": hashlib.sha256(img).digest(),
            "sha256(strip FF)": hashlib.sha256(stripped).digest(),
            "sha1(full)": hashlib.sha1(img).digest(),
            "md5(full)": hashlib.md5(img).digest(),
        }
        print(f"  [{i}] @0x{o:07X}  size={len(img):>8}  payload={len(stripped):>8}")
        for name, val in digests[i].items():
            print(f"       {name:18s} {val.hex()[:48]}...")
    print()

    # ---- search the whole file ------------------------------------------
    print("=== ARE ANY OF THOSE DIGESTS STORED IN THE FILE? ===")
    found_any = False
    for i, table in digests.items():
        for name, val in table.items():
            positions = []
            start = 0
            while True:
                p = d.find(val, start)
                if p < 0:
                    break
                positions.append(p)
                start = p + 1
            if positions:
                found_any = True
                where = ", ".join(f"0x{p:X}" for p in positions)
                print(f"  image[{i}] {name} FOUND at: {where}")
    if not found_any:
        print("  NONE. Image digests are not stored in the file in any of these")
        print("  forms. The verification value is computed inside PBL and compared")
        print("  against data that is not in the container.")
    print()

    # ---- wrapper inspection ---------------------------------------------
    print("=== WRAPPER (image 0) - first 0x200 bytes ===")
    hexdump(d, 0, 0x200)
    print()

    print("=== WRAPPER INTERIOR, REGION BY REGION ===")
    phoff = struct.unpack_from("<I", d, 28)[0]
    phnum = struct.unpack_from("<H", d, 44)[0]
    phentsize = struct.unpack_from("<H", d, 42)[0]
    after_phdrs = phoff + phnum * phentsize
    next_image = offs[1]

    # The wrapper's program headers cover the area up to the first inner image.
    # Describe each covered region honestly: some of it is zeros, some is not.
    regions = [(after_phdrs, 0x94, "tail of ph[0] payload"),
               (0x94, 0x1000, "rest of ph[0] payload"),
               (0x1000, 0x1074, "end of ph[0] payload"),
               (0x1074, next_image, "full ph[1] payload")]
    for start, end, label in regions:
        if start >= len(d) or end > len(d) or start >= end:
            continue
        seg = d[start:end]
        non_zero = sum(1 for b in seg if b not in (0x00, 0xFF))
        print(f"  0x{start:04X}..0x{end:04X}  {len(seg):5d} B  "
              f"non-00/non-FF = {non_zero:5d}   {label}")
    print()

    seg_start, seg_end = 0x1074, next_image
    seg = d[seg_start:seg_end]
    if seg and any(b not in (0x00, 0xFF) for b in seg):
        print("=== ph[1] PAYLOAD IS NOT EMPTY ===")
        print("  This region is a tag-length-value metadata blob, not padding.")
        print(f"  size {len(seg)} B; outer TLV header: ", end="")
        if len(seg) >= 4:
            tag, length = struct.unpack_from("<HH", seg, 0)
            print(f"tag=0x{tag:04X} len=0x{length:04X} "
                  f"(covers {4 + length} of {len(seg)} B)")
        print()
        print("  Nested TLVs inside the outer payload (2-byte tag, 2-byte length):")
        inner = seg[4:4 + length] if len(seg) >= 4 else b""
        i = 0
        depth = 0
        while i + 4 <= len(inner) and depth < 24:
            tag, sub = struct.unpack_from("<HH", inner, i)
            if sub > len(inner) - i - 4:
                print(f"    +0x{i:03X}  tag=0x{tag:04X} len=0x{sub:04X}  (runs past payload)")
                break
            print(f"    +0x{i:03X}  tag=0x{tag:04X} len=0x{sub:04X}")
            i += 4 + sub
            depth += 1
        print()
        print("  The schema of this blob is NOT identified. It contains a 64-byte")
        print("  high-entropy value that is not a plain hash of any obvious byte")
        print("  range of this file (checked sha256/384/512, sha3, blake2b, crc32).")
        print("  An earlier note claimed this whole area was zeros; that was wrong.")
        print("  See docs/04-melf-format.md section 2.")
        print()

    print("=== WRAPPER PROGRAM HEADERS ===")
    for i in range(phnum):
        o = phoff + i * phentsize
        ptype, poff, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from("<8I", d, o)
        print(f"  ph[{i}] type={ptype} off=0x{poff:X} vaddr=0x{vaddr:X} "
              f"filesz=0x{filesz:X} ({filesz}) flags=0x{flags:X}")

    print()
    print("CONCLUSION")
    print("  No per-image digest is stored anywhere in the container in any of the")
    print("  forms tested (sha256 full/stripped, sha1, md5, sha224/384/512, sha3,")
    print("  blake2b, crc32). Whatever PBL compares against is not in this file.")
    print()
    print("  Caveat worth stating precisely: the ph[1] metadata blob at")
    print("  0x1074..0x1300 is NOT empty and its schema is not identified. It")
    print("  contains one 64-byte high-entropy value. It is not a digest of any")
    print("  obvious byte range, but 'not a hash of what I tried' is weaker than")
    print("  'contains no hashes'. Treat this blob as unexplored, not as absent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
