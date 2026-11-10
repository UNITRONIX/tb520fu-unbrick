#!/usr/bin/env python3
"""compare_firmware.py - diff the DDR-relevant device tree across ROM versions.

Why this is worth doing
-----------------------
The recovery question is "why does DDR init not finish". If the 17.5 build trained
DDR successfully on the same silicon and the 18.5 build does not, then something in
the parameters changed. If both are identical, the parameter path is innocent and
the cause is elsewhere.

That is a cheap, decisive comparison, and it needs no device.

It extracts the DCB and pre-DDR DTB from each `xbl_config.elf` and compares:
  - the values of every DDR-relevant property
  - the presence of skip_ddr_init_in_EDL and ddr_boot_freq
  - the sizes and hashes of the payloads

Read-only, offline.

Usage
    python compare_firmware.py
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decode_fdt import Fdt  # noqa: E402

ROMS = {
    "18.5.10.037": Path(
        r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
        r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_config.elf"),
    "17.5.10.096": Path(
        r"C:\Users\UNITRONIX\Downloads\TB520FU_FW\096\TB520FU_ROW_OPEN_USER_Q00002.0_W_ZUI_17.5.10.096_ST_251127"
        r"\image\xbl_config.elf"),
}

#: Properties worth comparing. Anything DDR or boot-policy related.
WATCH = [
    "skip_ddr_init_in_EDL", "ddr_boot_freq", "ddr_log_level",
    "ddr_trng_always_en", "extnd_term_log_flag", "ddr_tr_led_flag",
    "print_severity", "skip-loader-dbc", "skip-core-dbc",
    "max-dbg-board-id", "min-dbg-board-id", "fedl_timeout",
]

#: Payload name -> the entry that points at it.
PAYLOADS = [
    b"A00C_8_0200_1_dcb.bin",
    b"A00C_8_0100_1_dcb.bin",
    b"pre-ddr-lanai-1.0.dtb",
    b"cpr.bin",
]


def extract(elf: bytes, name: bytes, base: int = 0x200):
    """Return (blob, off, len) for a named entry, offsets relative to `base`."""
    n = elf.find(name)
    if n < 0:
        return None
    for probe in range(n + len(name), min(n + len(name) + 64, len(elf) - 8)):
        off, ln = struct.unpack_from("<II", elf, probe)
        if not (0 < off < len(elf) and 0 < ln <= len(elf)):
            continue
        if off + ln > len(elf):
            continue
        # guard against picking up an unrelated pair
        if ln < 16:
            continue
        real = off + base
        if real + ln <= len(elf) and elf[real:real + 4] in (
                b"\xd0\x0d\xfe\xed", b"\x7fELF"):
            return elf[real:real + ln], real, ln
        if real + ln <= len(elf):
            return elf[real:real + ln], real, ln
    return None


def main() -> int:
    print("=" * 78)
    print("#  firmware comparison: DDR-relevant parameters")
    print("=" * 78)

    data = {}
    for label, path in ROMS.items():
        if not path.is_file():
            print(f"\n  {label}: MISSING ({path})")
            continue
        elf = path.read_bytes()
        print(f"\n  {label}: {len(elf)} B")
        entries = {}
        for name in PAYLOADS:
            r = extract(elf, name)
            if r is None:
                print(f"    {name.decode():<26} not found")
                continue
            blob, off, ln = r
            entries[name] = blob
            h = hashlib.sha256(blob).hexdigest()[:16]
            kind = "FDT" if blob[:4] == b"\xd0\x0d\xfe\xed" else "bin"
            print(f"    {name.decode():<26} {ln:>7} B  {kind}  sha256={h}")
        data[label] = entries

    if len(data) < 2:
        print("\n  need both ROMs to compare")
        return 1

    # ---- compare the device trees property by property ------------------
    print("\n" + "=" * 78)
    print("#  property comparison (DCB)")
    print("=" * 78)

    trees = {}
    for label, entries in data.items():
        blob = entries.get(b"A00C_8_0200_1_dcb.bin")
        if blob is None:
            continue
        try:
            trees[label] = Fdt(blob)
        except Exception as err:  # noqa: BLE001
            print(f"  {label}: not a valid FDT ({err})")

    if len(trees) == 2:
        labels = list(trees)
        a, b = labels
        pa = {(p, n): v for p, n, v in trees[a].walk()}
        pb = {(p, n): v for p, n, v in trees[b].walk()}
        keys = set(pa) | set(pb)

        print(f"\n  {a}: {len(pa)} properties")
        print(f"  {b}: {len(pb)} properties")

        only_a = [k for k in pa if k not in pb]
        only_b = [k for k in pb if k not in pa]
        diff = [k for k in keys if k in pa and k in pb and pa[k] != pb[k]]

        print(f"\n  properties only in {a}: {len(only_a)}")
        for p, n in sorted(only_a)[:20]:
            print(f"    /{p}:{n}")
        print(f"\n  properties only in {b}: {len(only_b)}")
        for p, n in sorted(only_b)[:20]:
            print(f"    /{p}:{n}")

        print(f"\n  properties differing in value: {len(diff)}")
        for p, n in sorted(diff)[:40]:
            va, vb = pa[(p, n)], pb[(p, n)]
            print(f"    /{p}:{n}")
            print(f"      {a}: {va.hex(' ')}")
            print(f"      {b}: {vb.hex(' ')}")

        print("\n#  watched properties")
        for w in WATCH:
            hits = [(p, pa.get((p, n)), pb.get((p, n)))
                    for p, n in keys if n == w]
            if not hits:
                continue
            for p, va, vb in hits:
                fa = int.from_bytes(va, "big") if va else None
                fb = int.from_bytes(vb, "big") if vb else None
                same = "same" if va == vb else "DIFFERENT"
                print(f"    /{p}:{w}")
                print(f"      {a}: {fa}   {b}: {fb}   -> {same}")

    print("\n" + "=" * 78)
    print("#  HOW TO READ THIS")
    print("=" * 78)
    print("  If the DDR parameters are identical across builds, then the parameters")
    print("  are not why one version trains and another does not - and the cause is")
    print("  in code or in device state, not in the device tree.")
    print()
    print("  If they differ, the differing property is a concrete candidate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
