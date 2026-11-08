#!/usr/bin/env python3
"""
melf_tool.py - inspect and manipulate a Qualcomm melf container.

A melf is an ELF32 wrapper with several inner ELF images concatenated after it.
On the TB520FU (SM8650), `xbl_s_devprg_ns.melf` contains five images, one of which
is the Firehose programmer. See docs/04-melf-format.md.

Subcommands
-----------
  info                            structure: wrapper, program headers, inner images
  split <outdir>                  extract every inner image to its own file
  patch <offset> <hex> <outfile>  write a copy with those bytes replaced
  verify                          check that reassembling the pieces reproduces the input

Usage
-----
  python melf_tool.py info  --melf path/to/xbl_s_devprg_ns.melf
  python melf_tool.py split --melf ... --out melf_parts
  python melf_tool.py patch --melf ... --offset 0x110B50 --hex 7f454c46 --out patched.melf
  python melf_tool.py verify --melf ...

Nothing in this tool writes to a device. It only reads and rewrites files.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
MACHINES = {
    0x01: "EM_ARM (32-bit)",
    0x03: "EM_386",
    0x28: "EM_ARM",
    0xB7: "EM_AARCH64 (64-bit)",
    0xF3: "vendor 0xF3 (Qualcomm)",
}
CLASSES = {1: "ELF32", 2: "ELF64"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_elf_offsets(data: bytes) -> list[int]:
    """Return offsets of plausible ELF headers (class 1 or 2, sane machine)."""
    out: list[int] = []
    i = 0
    while True:
        i = data.find(ELF_MAGIC, i)
        if i < 0:
            break
        if i + 20 <= len(data):
            cls = data[i + 4]
            machine = struct.unpack_from("<H", data, i + 18)[0]
            # machine 0x0000 is "no machine"; 0xFFFF and above are reserved
            if cls in (1, 2) and 0 < machine < 0x100:
                out.append(i)
        i += 4
    return out


def elf_info(data: bytes, off: int) -> dict:
    """Parse the fields we care about from an ELF header at `off`."""
    cls = data[off + 4]
    machine = struct.unpack_from("<H", data, off + 18)[0]
    etype = struct.unpack_from("<H", data, off + 16)[0]
    if cls == 1:
        entry = struct.unpack_from("<I", data, off + 24)[0]
        phoff = struct.unpack_from("<I", data, off + 28)[0]
        shoff = struct.unpack_from("<I", data, off + 32)[0]
        phentsize = struct.unpack_from("<H", data, off + 42)[0]
        phnum = struct.unpack_from("<H", data, off + 44)[0]
    else:
        entry = struct.unpack_from("<Q", data, off + 24)[0]
        phoff = struct.unpack_from("<Q", data, off + 32)[0]
        shoff = struct.unpack_from("<Q", data, off + 40)[0]
        phentsize = struct.unpack_from("<H", data, off + 54)[0]
        phnum = struct.unpack_from("<H", data, off + 56)[0]
    return dict(
        off=off,
        cls=cls,
        machine=machine,
        etype=etype,
        entry=entry,
        phoff=phoff,
        shoff=shoff,
        phentsize=phentsize,
        phnum=phnum,
    )


def describe_machine(machine: int) -> str:
    return MACHINES.get(machine, f"unknown 0x{machine:X}")


def cmd_info(melf: Path) -> int:
    data = melf.read_bytes()
    print(f"file      : {melf.name}")
    print(f"size      : {len(data)} B")
    print(f"sha256    : {sha(data)}")
    print()

    if data[:4] != ELF_MAGIC:
        print("ERROR: not an ELF file")
        return 2

    cls = data[4]
    machine = struct.unpack_from("<H", data, 18)[0]
    etype = struct.unpack_from("<H", data, 16)[0]
    entry = struct.unpack_from("<I", data, 24)[0] if cls == 1 else struct.unpack_from("<Q", data, 24)[0]
    phoff = struct.unpack_from("<I", data, 28)[0] if cls == 1 else struct.unpack_from("<Q", data, 32)[0]
    phentsize = struct.unpack_from("<H", data, 42)[0] if cls == 1 else struct.unpack_from("<H", data, 54)[0]
    phnum = struct.unpack_from("<H", data, 44)[0] if cls == 1 else struct.unpack_from("<H", data, 56)[0]

    print("=== OUTER HEADER (wrapper) ===")
    print(f"  class       : {CLASSES.get(cls, cls)}")
    print(f"  machine     : 0x{machine:02X}  {describe_machine(machine)}")
    print(f"  type        : {etype} (2=EXEC)")
    print(f"  entry       : 0x{entry:X}")
    print(f"  phoff       : 0x{phoff:X} ({phoff})")
    print(f"  phnum       : {phnum}  phentsize={phentsize}")
    print()

    print("=== PROGRAM HEADERS ===")
    covered = 0
    for i in range(phnum):
        o = phoff + i * phentsize
        if cls == 1:
            ptype, poff, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from("<8I", data, o)
        else:
            ptype, flags = struct.unpack_from("<II", data, o)
            poff, vaddr, paddr = struct.unpack_from("<QQQ", data, o + 8)
            filesz, memsz, align = struct.unpack_from("<QQQ", data, o + 32)
        covered = max(covered, poff + filesz)
        print(f"  ph[{i}] type={ptype} off=0x{poff:X} vaddr=0x{vaddr:X} "
              f"filesz=0x{filesz:X} ({filesz}) memsz=0x{memsz:X} flags=0x{flags:X}")
    print(f"  -> headers cover 0x0 .. 0x{covered:X} ({covered})")
    print()

    print("=== INNER ELF IMAGES ===")
    offs = find_elf_offsets(data)
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(data)
        size = end - o
        inf = elf_info(data, o)
        print(f"  [{i}] @0x{o:07X}  {CLASSES.get(inf['cls'], '?'):6s} "
              f"machine=0x{inf['machine']:02X} {describe_machine(inf['machine']):20s} "
              f"entry=0x{inf['entry']:X}  size=0x{size:X} ({size})")
    print()

    if len(offs) > 1:
        first_inner = offs[1] if offs[0] == 0 else offs[0]
        print("=== APPENDED BLOB ===")
        print(f"  data from 0x{first_inner:X} to end: {len(data) - first_inner} B")
        print("  (this is the 'multi-image' region: consecutive images back to back)")
        print()

    # Trailing padding: useful because Sahara never requests it
    if offs:
        last = offs[-1]
        img = data[last:]
        ff_tail = len(img) - len(img.rstrip(b"\xff"))
        print("=== TRAILING PADDING ===")
        print(f"  last image at 0x{last:X}, ends with {ff_tail} B of 0xFF")
    return 0


def cmd_split(melf: Path, outdir: Path) -> int:
    data = melf.read_bytes()
    offs = find_elf_offsets(data)
    if not offs:
        print("ERROR: no ELF images found")
        return 2

    outdir.mkdir(parents=True, exist_ok=True)
    print(f"extracting {len(offs)} images into {outdir}")

    rows = []
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(data)
        blob = data[o:end]
        inf = elf_info(data, o)
        name = f"img{i}_0x{o:07X}_{CLASSES.get(inf['cls'], 'x').lower()}_m{inf['machine']:02x}.elf"
        (outdir / name).write_bytes(blob)
        rows.append((name, len(blob), inf["entry"], sha(blob)))
        print(f"  {name}  {len(blob)} B  entry=0x{inf['entry']:X}")

    print()
    print("=== SUMMARY ===")
    for name, size, entry, digest in rows:
        print(f"  {name}")
        print(f"     {size} B  entry=0x{entry:X}  sha256={digest[:32]}...")
    return 0


def cmd_patch(melf: Path, offset: str, hexbytes: str, out: Path) -> int:
    data = bytearray(melf.read_bytes())
    off = int(offset, 0)
    new = bytes.fromhex(hexbytes)
    if off + len(new) > len(data):
        print(f"ERROR: offset 0x{off:X} + {len(new)} exceeds file size {len(data)}")
        return 2
    old = bytes(data[off:off + len(new)])
    data[off:off + len(new)] = new
    out.write_bytes(data)
    print(f"patch : 0x{off:X}  {old.hex()} -> {new.hex()}")
    print(f"wrote : {out} ({len(data)} B)")
    print(f"sha256: {sha(bytes(data))}")
    return 0


def cmd_verify(melf: Path) -> int:
    """Confirm we understand the format: pieces reassemble to the original."""
    data = melf.read_bytes()
    print("=== FORMAT UNDERSTANDING CHECK ===")
    print(f"original : {len(data)} B  sha256={sha(data)}")

    offs = find_elf_offsets(data)
    if not offs:
        print("ERROR: no ELF images found")
        return 2

    rebuilt = bytearray()
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(data)
        if len(rebuilt) < o:
            rebuilt.extend(data[len(rebuilt):o])
        rebuilt.extend(data[o:end])

    ok = bytes(rebuilt) == data
    print(f"rebuilt  : {len(rebuilt)} B  sha256={sha(bytes(rebuilt))}")
    print(f"IDENTICAL: {ok}")
    if not ok:
        for i in range(min(len(data), len(rebuilt))):
            if data[i] != rebuilt[i]:
                print(f"  first difference @0x{i:X}: {data[i]:02x} vs {rebuilt[i]:02x}")
                break
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Inspect and manipulate a Qualcomm melf container.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("command", choices=["info", "split", "patch", "verify"])
    ap.add_argument("--melf", required=True, type=Path,
                    help="path to the .melf file")
    ap.add_argument("--out", type=Path,
                    help="output directory (split) or file (patch)")
    ap.add_argument("--offset", help="byte offset for patch, e.g. 0x110B50")
    ap.add_argument("--hex", help="replacement bytes as hex, e.g. 7f454c46")
    args = ap.parse_args(argv)

    if not args.melf.is_file():
        print(f"ERROR: no such file: {args.melf}")
        return 2

    if args.command == "info":
        return cmd_info(args.melf)
    if args.command == "split":
        return cmd_split(args.melf, args.out or Path("melf_parts"))
    if args.command == "patch":
        if not args.offset or not args.hex or not args.out:
            print("ERROR: patch requires --offset, --hex and --out")
            return 2
        return cmd_patch(args.melf, args.offset, args.hex, args.out)
    return cmd_verify(args.melf)


if __name__ == "__main__":
    sys.exit(main())
