#!/usr/bin/env python3
"""decode_fdt.py - read the DCB and pre-DDR DTB as flattened device trees.

Both payloads extracted from xbl_config.elf are FDT blobs (magic d00dfeed,
version 0x11):

    A00C_8_0200_1_dcb.bin   28 695 B   the DDR configuration block
    pre-ddr-lanai-1.0.dtb   73 258 B   board DDR topology

An FDT is self-describing: a structure block of nodes and properties, plus a
string table. That means these can be read as data rather than reverse-engineered
blind - which is a different situation from every other artefact in this project.

What to look for
----------------
The DDR training failure question needs the declared memory part, the frequency
plan and the training parameters. Those appear as properties under nodes like
/soc/ddr, /memory, or a board-specific DDR node.

Read-only, offline.

Usage
    python decode_fdt.py                 # summary + interesting properties
    python decode_fdt.py --all           # every property
    python decode_fdt.py --node /soc/ddr # one subtree
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAYLOADS = HERE / "xbl_config_payloads"

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


class Fdt:
    def __init__(self, blob: bytes) -> None:
        (magic, self.total, off_struct, off_strings, off_rsv,
         self.version, self.last_comp, boot_cpuid, size_strings,
         size_struct) = struct.unpack_from(">IIIIIIIIII", blob, 0)
        if magic != FDT_MAGIC:
            raise ValueError(f"bad FDT magic {magic:#x}")
        self.blob = blob
        self.struct_blk = blob[off_struct:off_struct + size_struct]
        self.strings = blob[off_strings:off_strings + size_strings]

    def _str(self, off: int) -> str:
        end = self.strings.find(b"\x00", off)
        return self.strings[off:end if end >= 0 else None].decode("ascii", "replace")

    def walk(self):
        """Yield (path, prop_name, value_bytes) for every property."""
        pos = 0
        stack: list[str] = []
        blk = self.struct_blk
        while pos + 4 <= len(blk):
            tok = struct.unpack_from(">I", blk, pos)[0]
            pos += 4
            if tok == FDT_BEGIN_NODE:
                end = blk.find(b"\x00", pos)
                name = blk[pos:end].decode("ascii", "replace")
                pos = (end + 4) & ~3
                # root node has an empty name
                stack.append(name or "/")
            elif tok == FDT_END_NODE:
                if stack:
                    stack.pop()
            elif tok == FDT_PROP:
                if pos + 8 > len(blk):
                    break
                ln, nameoff = struct.unpack_from(">II", blk, pos)
                pos += 8
                val = blk[pos:pos + ln]
                pos = (pos + ln + 3) & ~3
                yield "/".join(s for s in stack if s != "/") or "/", \
                    self._str(nameoff), val
            elif tok == FDT_NOP:
                continue
            elif tok == FDT_END:
                break
            else:
                break


def fmt_value(v: bytes) -> str:
    if not v:
        return "<empty>"
    # printable string, possibly NUL-separated list
    if all(32 <= x < 127 or x == 0 for x in v) and v[-1] == 0:
        parts = [p.decode("ascii", "replace") for p in v.split(b"\x00") if p]
        if parts:
            return " + ".join(f'"{p}"' for p in parts[:6])
    if len(v) % 4 == 0 and len(v) <= 32:
        nums = struct.unpack(f">{len(v)//4}I", v)
        return " ".join(f"{n:#x}" for n in nums)
    if v:
        return f"<{len(v)} B> {v[:24].hex(' ')}"
    return "<empty>"


#: Property/node names that carry DDR-relevant meaning.
INTERESTING = [
    "ddr", "DDR", "freq", "Freq", "clock", "mem", "Mem", "memory",
    "train", "Train", "vref", "Vref", "vbat", "VBAT", "volt", "Volt",
    "lp5", "LP5", "shrm", "SHRM", "dcb", "DCB", "manufacturer", "part",
    "size", "reg", "compatible", "model", "speed", "timing", "Timing",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--node", default=None, help="only properties under this path")
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    files = [Path(args.file)] if args.file else [
        PAYLOADS / "A00C_8_0200_1_dcb.bin",
        PAYLOADS / "pre-ddr-lanai-1.0.dtb",
    ]

    for f in files:
        if not f.is_file():
            print(f"missing {f} - run extract_xbl_config.py first")
            continue
        print("=" * 78)
        print(f"#  {f.name}  {f.stat().st_size} B")
        print("=" * 78)
        try:
            fdt = Fdt(f.read_bytes())
        except Exception as err:  # noqa: BLE001
            print(f"  not a valid FDT: {err}")
            continue
        print(f"  FDT version={fdt.version} totalsize={fdt.total}")

        props = list(fdt.walk())
        nodes = sorted({p for p, _, _ in props})
        print(f"  properties={len(props)}  nodes={len(nodes)}")

        if args.all or args.node:
            for path, name, val in props:
                if args.node and not path.startswith(args.node.strip("/")):
                    continue
                print(f"  /{path}:{name} = {fmt_value(val)}")
            print()
            continue

        print("\n#  nodes")
        for n in nodes[:60]:
            print(f"  /{n}")
        if len(nodes) > 60:
            print(f"  ... {len(nodes) - 60} more")

        print("\n#  DDR-relevant properties")
        shown = 0
        for path, name, val in props:
            hit = any(k in name for k in INTERESTING) or \
                  any(k in path for k in ("ddr", "DDR", "memory", "mem"))
            if not hit:
                continue
            print(f"  /{path}:{name} = {fmt_value(val)}")
            shown += 1
            if shown > 140:
                print("  ... truncated (use --all)")
                break
        print()

    print("=" * 78)
    print("#  WHY THIS IS THE RIGHT PLACE TO WORK")
    print("=" * 78)
    print("  These are the exact payloads the devprg loads before training DDR.")
    print("  They are plain device trees, so every declared value is readable -")
    print("  part numbers, frequencies, voltages, training flags.")
    print()
    print("  That turns 'DDR training probably fails' into a comparison: what the")
    print("  board declares here, versus what the silicon reports back. The")
    print("  interesting mismatch, if any, will be visible in this output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
