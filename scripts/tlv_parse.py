#!/usr/bin/env python3
"""Independent TLV parser for the melf wrapper payload (ph[1] @0x1074..0x1300)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

MELF = Path(sys.argv[1] if len(sys.argv) > 1 else
            r"C:\ProgramData\RSA\Download\RomFiles"
            r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
            r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
            r"\image\xbl_s_devprg_ns.melf")


def parse(buf: bytes, base: int, depth: int = 0, limit: int = 8):
    """TLV: tag u16 LE, len u16 LE, value, padded to 4 bytes."""
    pos = 0
    out = []
    while pos + 4 <= len(buf):
        tag, ln = struct.unpack_from("<HH", buf, pos)
        vstart = pos + 4
        vend = vstart + ln
        if vend > len(buf):
            out.append((base + pos, tag, ln, None, "OVERFLOW"))
            break
        value = buf[vstart:vend]
        out.append((base + pos, tag, ln, value, "ok"))
        pos = vstart + ((ln + 3) // 4) * 4
    return out, pos


def walk(buf: bytes, base: int, depth: int = 0, maxdepth: int = 4):
    items, used = parse(buf, base)
    for off, tag, ln, value, status in items:
        pad = "  " * depth
        shape = ""
        if value is not None and ln >= 8:
            # does it look like a nested TLV container?
            t2, l2 = struct.unpack_from("<HH", value, 0)
            if 0 < l2 <= ln - 4:
                sub, subused = parse(value, base + (off - base) + 4)
                if len(sub) > 1 and subused == len(value):
                    shape = f"  container({len(sub)} children)"
        print(f"{pad}{off:#06x} tag={tag:#06x} len={ln:4d} {status}{shape}")
        if shape and depth < maxdepth:
            walk(value, off + 4, depth + 1, maxdepth)
        elif value is not None and 0 < ln <= 64:
            print(f"{pad}         value={value.hex()}")


data = MELF.read_bytes()
blob = data[0x1074:0x1300]
print(f"file     : {MELF}")
print(f"size     : {len(data)}")
print(f"TLV      : 0x1074..0x1300  ({len(blob)} B)")
print()
walk(blob, 0x1074)
