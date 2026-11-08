#!/usr/bin/env python3
"""Verify three claims about the TB520FU melf wrapper TLV.

Error 1: SWITCH_MODE packet length (12 vs 16 bytes) - checked from logs, not here.
Error 2: are the high-entropy TLV blocks hashes of something real?
Error 3: is the TLV byte-identical across three different ROM builds?
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

FILES = {
    "ZUI 18.5.10.037 (A17)": Path(
        r"C:\ProgramData\RSA\Download\RomFiles"
        r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
        r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
        r"\image\xbl_s_devprg_ns.melf"),
    "ZUI 17.5.10.096": Path(
        r"C:\Users\UNITRONIX\Downloads\TB520FU_FW\096"
        r"\TB520FU_ROW_OPEN_USER_Q00002.0_W_ZUI_17.5.10.096_ST_251127"
        r"\image\xbl_s_devprg_ns.melf"),
    "stock_18.5_ref": Path(
        r"C:\Users\UNITRONIX\Downloads\TB520FU_FW"
        r"\backup_pre_096_20261025_205920\stock_18.5_ref"
        r"\xbl_s_devprg_ns.melf"),
}

TLV_START, TLV_END = 0x1074, 0x1300

# ELF image boundaries inside the melf (from the ELF header scan).
IMAGES = [
    ("wrapper",   0x000000, 4864),
    ("image[1]",  0x001300, 193600),
    ("image[2]",  0x032F70, 1105776),
    ("firehose",  0x110B50, 1416016),
    ("ddr",       0x15AB48, 1563244),
]


def sha(alg: str, data: bytes) -> str:
    h = hashlib.new(alg)
    h.update(data)
    return h.hexdigest()


def tlv_blocks(blob: bytes) -> dict[int, bytes]:
    """Flat map offset -> value for every TLV in the region (recursive)."""
    out: dict[int, bytes] = {}

    def walk(buf: bytes, base: int) -> None:
        pos = 0
        while pos + 4 <= len(buf):
            tag, ln = struct.unpack_from("<HH", buf, pos)
            vs = pos + 4
            ve = vs + ln
            if ve > len(buf):
                return
            value = buf[vs:ve]
            out[base + pos] = value
            # try to descend if the value itself looks like a TLV container
            if ln >= 8:
                t2, l2 = struct.unpack_from("<HH", value, 0)
                if 0 < l2 <= ln - 4:
                    walk(value, base + pos + 4)
            pos = vs + ((ln + 3) // 4) * 4

    walk(blob, TLV_START)
    return out


def main() -> None:
    data = {}
    for name, path in FILES.items():
        if not path.exists():
            print(f"BRAK: {name}")
            continue
        data[name] = path.read_bytes()

    print("=" * 78)
    print("ERROR 3 — is the TLV identical across builds?")
    print("=" * 78)
    for name, d in data.items():
        tlv = d[TLV_START:TLV_END]
        print(f"  {name:26s} size={len(d):>9d}  "
              f"file_sha256={sha('sha256', d)[:16]}  "
              f"tlv_sha256={sha('sha256', tlv)[:16]}")

    names = list(data)
    if len(names) >= 2:
        a, b = names[0], names[1]
        da, db = data[a], data[b]
        diffs = [i for i in range(min(len(da), len(db))) if da[i] != db[i]]
        print(f"\n  diff {a} vs {b}: {len(diffs)} differing bytes")
        if diffs:
            print(f"    first={diffs[0]:#x}  last={diffs[-1]:#x}")
            inside = [i for i in diffs if TLV_START <= i < TLV_END]
            print(f"    inside TLV 0x{TLV_START:x}..0x{TLV_END:x}: {len(inside)}")
        tlv_equal = da[TLV_START:TLV_END] == db[TLV_START:TLV_END]
        print(f"    TLV identical: {tlv_equal}")

    print()
    print("=" * 78)
    print("ERROR 2 — do the high-entropy TLV blocks match anything?")
    print("=" * 78)

    d = data[names[0]]
    blob = d[TLV_START:TLV_END]
    blocks = tlv_blocks(blob)

    # collect the interesting blocks by tag
    interesting = {}
    for off, value in blocks.items():
        if off + 4 > TLV_END:
            continue
        tag = struct.unpack_from("<H", d, off)[0]
        if tag in (0x8441, 0x81FF) and len(value) >= 32:
            interesting.setdefault(tag, []).append((off, value))

    for tag, items in interesting.items():
        for off, value in items:
            print(f"  tag {tag:#06x} @ {off:#06x}  len={len(value)}  "
                  f"head={value[:16].hex()}")

    # build candidate payloads
    candidates = {}
    for name, start, end in IMAGES:
        raw = d[start:end]
        candidates[f"{name} full"] = raw
        candidates[f"{name} stripped_ff"] = raw.rstrip(b"\xff")
        candidates[f"{name} stripped_00"] = raw.rstrip(b"\x00")
    candidates["whole TLV"] = blob
    candidates["whole file"] = d
    for name, start, end in IMAGES:
        candidates[f"{name} exact"] = d[start:end]

    print()
    print("  Testing 64-byte block (tag 0x8441):")
    for off, value in interesting.get(0x8441, []):
        if len(value) != 64:
            continue
        hit = False
        for cname, cdata in candidates.items():
            for alg in ("sha512", "sha3_512", "blake2b"):
                if sha(alg, cdata) == value.hex():
                    print(f"    MATCH {alg} of {cname}")
                    hit = True
            for alg in ("sha256", "sha3_256"):
                if sha(alg, cdata).ljust(64, "0")[:64] == value.hex():
                    print(f"    MATCH {alg} (padded) of {cname}")
                    hit = True
        if not hit:
            print(f"    no match among {len(candidates)} candidates "
                  f"x 3 algorithms")

    print()
    print("  Testing 136-byte blocks (tag 0x81FF):")
    for off, value in interesting.get(0x81FF, []):
        if len(value) < 132:
            continue
        idx = struct.unpack_from("<I", value, 0)[0]
        part1 = value[4:68]
        part2 = value[68:132]
        print(f"    @{off:#06x} index={idx}  part1={part1[:8].hex()}...  "
              f"part2={part2[:8].hex()}...")
        hits = 0
        for cname, cdata in candidates.items():
            for alg in ("sha512", "sha3_512"):
                h = sha(alg, cdata)
                if h == part1.hex():
                    print(f"      part1 == {alg} of {cname}")
                    hits += 1
                if h == part2.hex():
                    print(f"      part2 == {alg} of {cname}")
                    hits += 1
        if not hits:
            print(f"      no match (checked {len(candidates)} candidates)")


if __name__ == "__main__":
    main()
