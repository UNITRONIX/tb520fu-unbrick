#!/usr/bin/env python3
"""extract_xbl_config.py - pull the DCB and pre-DDR DTB out of xbl_config.elf.

Why this matters
----------------
The DDR bring-up inside the devprg reads, by name:

    A00C_8_0200_1_dcb.bin      DDR configuration block (memory part + timings)
    A00C_8_0100_1_dcb.bin
    pre-ddr-lanai-1.0.dtb      board DDR topology
    /cpr.bin

and the devprg itself reports "CDT not found in any storage media, using
defaults" - so it has a fallback path, and the fallback depends on exactly these
payloads being present and correct.

They are NOT in the melf as loose blobs: they are entries in `xbl_config.elf`,
which uses a simple name table with (offset, length) pairs. dcb_locator.py found
the names; this extracts what they point at.

The point is not curiosity. If the DCB names a memory part or a frequency that
this board cannot run, DDR training fails, the programmer never raises USB, and
the symptom is exactly the watchdog at ~7.9 s that we measure. A DCB that can be
inspected makes that testable.

Read-only, offline. Writes extracted payloads next to itself.

Usage
    python extract_xbl_config.py
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

DEFAULT = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_config.elf"
)
OUT = Path(__file__).resolve().parent / "xbl_config_payloads"


def read_name(data: bytes, off: int, limit: int = 64) -> str:
    end = data.find(b"\x00", off)
    if end < 0:
        return ""
    return data[off:end].decode("ascii", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    ap.add_argument("--elf-header", action="store_true",
                    help="describe the ELF program headers first")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    data = path.read_bytes()
    OUT.mkdir(exist_ok=True)

    print("=" * 78)
    print(f"#  {path.name}  {len(data)} B")
    print("=" * 78)

    if data[:4] == b"\x7fELF" and args.elf_header:
        cls = data[4]
        print(f"  ELF class={cls}")
        if cls == 2:
            e_phoff = struct.unpack_from("<Q", data, 32)[0]
            e_phnum = struct.unpack_from("<H", data, 56)[0]
            e_phentsize = struct.unpack_from("<H", data, 54)[0]
        else:
            e_phoff = struct.unpack_from("<I", data, 28)[0]
            e_phnum = struct.unpack_from("<H", data, 44)[0]
            e_phentsize = struct.unpack_from("<H", data, 42)[0]
        print(f"  phoff={e_phoff:#x} phnum={e_phnum} entsize={e_phentsize}")
        for i in range(e_phnum):
            o = e_phoff + i * e_phentsize
            if o + e_phentsize > len(data):
                break
            if cls == 2:
                p_type = struct.unpack_from("<I", data, o)[0]
                p_off, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from(
                    "<QQQQQ", data, o + 8)
            else:
                p_type = struct.unpack_from("<I", data, o)[0]
                p_off, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from(
                    "<IIIII", data, o + 4)
            if p_filesz:
                print(f"    ph[{i}] type={p_type:#x} off={p_off:#x} "
                      f"vaddr={p_vaddr:#x} paddr={p_paddr:#x} filesz={p_filesz:#x}")

    # ---- find every entry: name, then offset, then length ---------------
    # The table observed in xbl_config.elf looks like:
    #   "A00C_8_0200_1_dcb.bin\0\0\0\0"  <u32 off> <u32 len>
    # with off/len appearing after the NUL padding. Rather than assume a fixed
    # header layout, scan for each known name and take the first plausible
    # (off, len) pair in the 32 bytes that follow it.
    names = [
        "A00C_8_0200_1_dcb.bin",
        "A00C_8_0100_1_dcb.bin",
        "pre-ddr-lanai-1.0.dtb",
        "lanai-1.0.dtb",
        "dcb.bin",
        "cpr.bin",
    ]

    print("\n#  entries found")
    print(f"  {'name':<26} {'name@':>10} {'offset':>10} {'length':>10} {'end':>10}")
    print("  " + "-" * 70)

    extracted = []
    for name in names:
        n_off = data.find(name.encode())
        if n_off < 0:
            print(f"  {name:<26} {'absent':>10}")
            continue
        pair = None
        for probe in range(n_off + len(name), min(n_off + len(name) + 40, len(data) - 8)):
            off, ln = struct.unpack_from("<II", data, probe)
            if 0 < off < len(data) and 0 < ln <= len(data) and off + ln <= len(data):
                pair = (off, ln)
                break
        if not pair:
            print(f"  {name:<26} {n_off:#10x} {'no pair':>10}")
            continue
        off, ln = pair
        # MEASURED: these offsets are relative to the start of the segment area
        # at 0x200, not to the file. Verified against the ELF program headers:
        #   dcb    0xc918 + 0x200 = 0xcb18 = ph[3].off, len 0x7018 = ph[3].filesz
        #   dtb    0x13930 + 0x200 = 0x13b30 = ph[4].off, len 0x11e2c = ph[4].filesz
        # Using the raw value silently shifts every payload by 0x200 and makes a
        # DCB look like a string table. That mistake was made once here.
        base_off = 0x200
        off += base_off
        print(f"  {name:<26} {n_off:#10x} {off:#10x} {ln:#10x} {off + ln:#10x}")
        blob = data[off:off + ln]
        safe = name.replace("/", "_")
        (OUT / safe).write_bytes(blob)
        extracted.append((name, off, ln, blob))

    # ---- characterise what came out -------------------------------------
    print("\n#  payload characteristics")
    for name, off, ln, blob in extracted:
        head = blob[:16]
        kind = "?"
        if head[:4] == b"\xd0\x0d\xfe\xed":
            kind = "FDT/DTB (devicetree blob)"
        elif head[:4] == b"\x7fELF":
            kind = "ELF"
        else:
            nz = sum(1 for x in blob if x)
            kind = f"data (nonzero {nz/len(blob):.0%})"
        print(f"  {name:<26} {len(blob):>7d} B  {kind}")
        print(f"      head: {head.hex(' ')}")
        if kind.startswith("FDT"):
            magic, totalsize, off_struct, off_strings, off_rsv, version = \
                struct.unpack_from(">IIIIII", blob, 0)
            print(f"      FDT totalsize={totalsize} version={version:#x}")

    print(f"\n  extracted to: {OUT}")
    print("\n" + "=" * 78)
    print("#  NEXT")
    print("=" * 78)
    print("  The DTB is a devicetree, so it can be decompiled and compared against")
    print("  the board. The DCB is the memory parameter block the training uses;")
    print("  if its part number or frequency does not match this board, that is a")
    print("  direct, checkable cause for the programmer's silent death.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
