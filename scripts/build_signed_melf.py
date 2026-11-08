#!/usr/bin/env python3
"""
build_signed_melf.py - rebuild a melf with one inner image replaced.

This reproduces the experiment that closed the image-substitution route. It builds
a structurally valid container: same wrapper, same untouched images, one image
swapped, all program headers still in bounds. The device rejects it with 0x21 at
an offset BEFORE the swapped image, which is how we know the integrity check
covers the whole blob rather than individual images.

The tool is included because reproducing that result takes minutes and settles the
question for a given firmware revision. It is NOT a path to a working programmer.

Usage
-----
  python build_signed_melf.py --melf path/to/xbl_s_devprg_ns.melf \
      --replace path/to/prog_firehose_ddr-signed-v7.mbn \
      --out xbl_s_devprg_ns_SIGNED_FH.melf

  # keep the total size identical (trim trailing zeros from the replacement)
  python build_signed_melf.py ... --pad-to-original
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"

#: Default layout of xbl_s_devprg_ns.melf on SM8650 / TB520FU.
#: Confirmed with melf_tool.py info; override with --image-offset if yours differs.
DEFAULT_WRAPPER_END = 0x1300
DEFAULT_IMAGE_OFF = 0x110B50   # the Firehose image
DEFAULT_IMAGE_END = 0x15AB48   # where the DDR-training image begins


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_image_bounds(data: bytes, target_offset: int | None) -> tuple[int, int, int]:
    """Return (wrapper_end, image_start, image_end) for the image to replace."""
    offs = []
    i = 0
    while True:
        i = data.find(ELF_MAGIC, i)
        if i < 0:
            break
        if i + 20 <= len(data) and data[i + 4] in (1, 2):
            offs.append(i)
        i += 4

    if not offs:
        raise ValueError("no ELF images found in the container")

    start = target_offset if target_offset is not None else DEFAULT_IMAGE_OFF
    if start not in offs:
        raise ValueError(
            f"offset 0x{start:X} is not an image boundary; found: "
            + ", ".join(f"0x{o:X}" for o in offs)
        )
    idx = offs.index(start)
    end = offs[idx + 1] if idx + 1 < len(offs) else len(data)
    wrapper_end = offs[1] if len(offs) > 1 else DEFAULT_WRAPPER_END
    return wrapper_end, start, end


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rebuild a melf with one inner image replaced.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--melf", required=True, type=Path,
                    help="the original melf container")
    ap.add_argument("--replace", required=True, type=Path,
                    help="the file to put in place of the chosen image")
    ap.add_argument("--out", required=True, type=Path,
                    help="output melf path")
    ap.add_argument("--image-offset", type=lambda s: int(s, 0), default=None,
                    help=f"offset of the image to replace "
                         f"(default 0x{DEFAULT_IMAGE_OFF:X})")
    ap.add_argument("--pad-to-original", action="store_true",
                    help="trim trailing zero bytes from the replacement so the "
                         "total file size is unchanged")
    args = ap.parse_args(argv)

    for p in (args.melf, args.replace):
        if not p.is_file():
            print(f"ERROR: no such file: {p}")
            return 2

    data = args.melf.read_bytes()
    replacement = args.replace.read_bytes()

    print(f"original melf     : {args.melf.name}  {len(data)} B")
    print(f"                  sha256={sha(data)[:32]}...")
    print(f"replacement image : {args.replace.name}  {len(replacement)} B")
    print(f"                  sha256={sha(replacement)[:32]}...")
    print()

    try:
        wrapper_end, img_start, img_end = find_image_bounds(data, args.image_offset)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    if args.pad_to_original:
        target_len = img_end - img_start
        if len(replacement) > target_len:
            trimmed = replacement.rstrip(b"\x00")
            if len(trimmed) <= target_len:
                removed = len(replacement) - len(trimmed)
                print(f"padded mode: trimmed {removed} trailing zero bytes from the "
                      f"replacement ({len(replacement)} -> {len(trimmed)} B)")
                replacement = trimmed
            else:
                print(f"WARNING: replacement is {len(replacement)} B and the slot is "
                      f"{target_len} B; cannot fit after trimming ({len(trimmed)} B)")
        elif len(replacement) < target_len:
            pad = target_len - len(replacement)
            print(f"padded mode: appending {pad} zero bytes to fill the slot")
            replacement = replacement + b"\x00" * pad

    # ---- assemble --------------------------------------------------------
    wrapper = data[:wrapper_end]
    before = data[wrapper_end:img_start]
    original_image = data[img_start:img_end]
    after = data[img_end:]

    new_data = wrapper + before + replacement + after
    args.out.write_bytes(new_data)

    print()
    print("=== PIECES ===")
    print(f"  wrapper (untouched)      : {len(wrapper)} B")
    print(f"  images before target     : {len(before)} B")
    print(f"  original target image    : {len(original_image)} B")
    print(f"  new target image         : {len(replacement)} B "
          f"({len(replacement) - len(original_image):+d})")
    print(f"  images after target      : {len(after)} B")
    print()
    print("=== RESULT ===")
    print(f"  file   : {args.out}")
    print(f"  size   : {len(new_data)} B "
          f"(original {len(data)}, delta {len(new_data) - len(data):+d})")
    print(f"  sha256 : {sha(new_data)}")

    # ---- verification ----------------------------------------------------
    print()
    print("=== VERIFICATION ===")
    checks = {
        "wrapper untouched": new_data[:wrapper_end] == wrapper,
        "earlier images untouched": new_data[wrapper_end:img_start] == before,
        "replacement written":
            new_data[img_start:img_start + len(replacement)] == replacement,
        "later images untouched":
            new_data[img_start + len(replacement):] == after,
    }
    in_bounds = True
    phoff = struct.unpack_from("<I", new_data, 28)[0]
    phnum = struct.unpack_from("<H", new_data, 44)[0]
    for i in range(phnum):
        o = phoff + i * 32
        _ptype, poff, _vaddr, _paddr, filesz, _memsz, _flags, _align = struct.unpack_from("<8I", new_data, o)
        if poff + filesz > len(new_data):
            in_bounds = False
    checks["all program headers in bounds"] = in_bounds

    for name, ok in checks.items():
        print(f"  {name:34s} {'PASS' if ok else 'FAIL'}")

    if all(checks.values()):
        print()
        print("Structurally valid container built.")
        print()
        print("Expect this to be REJECTED by the device with 0x21. That is the")
        print("point: the transfer will die at an offset before the replacement,")
        print("proving the container is verified as a whole. See")
        print("  docs/04-melf-format.md  section 5")
        return 0

    print()
    print("Build is not valid; do not use this file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
