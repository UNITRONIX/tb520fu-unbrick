#!/usr/bin/env python3
"""find_live_vbat.py - is there a live battery voltage anywhere the dump exposes?

Why this specific hunt
----------------------
docs/19-battery-gate.md establishes that the battery gate runs in XBL, before
Firehose, and that a refusal there would produce exactly the silence-then-watchdog
we measure. The missing measurement is a live VBAT figure on this unit.

The crash dump exposes 53 named regions. Two are promising:

  sbl_pmic_dump.bin   512 KiB "SBL PMIC dump" - a structured register capture
  SHRM_MEM.BIN        256 KiB shared memory

`sbl_pmic_dump` was already checked for text and is not a log: it opens with
`03 00 00 00 52 44 00 00 53 42 4c 00` - i.e. a header with "RD" and "SBL" - then a
dense structure. That shape is consistent with a *register map*, which is exactly
where an ADC result would sit.

This scans it for values in a plausible battery-voltage range and reports where
runs of them cluster, then cross-checks against SHRM_MEM.

Read-only, offline. Uses the dumps already on disk.

Usage
    python find_live_vbat.py
"""
from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMPS = {
    "sbl_pmic_dump": HERE / "pmic_state_probe" / "sbl_pmic_dump.bin",
    "SHRM_MEM": HERE / "pmic_state_probe" / "SHRM_MEM.BIN",
}

#: Plausible single-cell Li-ion range, in millivolts.
VBAT_LO, VBAT_HI = 3000, 4600

#: The header we expect from the SBL dump.
SBL_HDR = bytes.fromhex("03000000 52440000 53424c00".replace(" ", ""))


def scan_u16(blob: bytes, lo: int, hi: int) -> list[tuple[int, int]]:
    """Return (offset, value) for u16 values inside [lo, hi]."""
    out = []
    for off in range(0, len(blob) - 2, 2):
        v = struct.unpack_from("<H", blob, off)[0]
        if lo <= v <= hi:
            out.append((off, v))
    return out


def main() -> int:
    print("=" * 78)
    print("#  hunting a live battery voltage in the dumps we already hold")
    print("=" * 78)

    for name, path in DUMPS.items():
        if not path.is_file():
            print(f"\n  {name}: missing ({path.name}) - run pmic_state_probe.py first")
            continue
        blob = path.read_bytes()
        print(f"\n  {name}: {len(blob)} B")

        if name == "sbl_pmic_dump":
            print(f"    header matches expectation: {blob[:12] == SBL_HDR}")
            print(f"    first 12 bytes: {blob[:12].hex(' ')}")

        hits = scan_u16(blob, VBAT_LO, VBAT_HI)
        print(f"    u16 values in {VBAT_LO}..{VBAT_HI} mV: {len(hits)}")

        if not hits:
            print("    none - no battery-range value present in this region")
            continue

        # cluster by proximity: a register block would hold several together
        clusters: list[list[tuple[int, int]]] = []
        cur = [hits[0]]
        for prev, nxt in zip(hits, hits[1:]):
            if nxt[0] - prev[0] <= 32:
                cur.append(nxt)
            else:
                clusters.append(cur)
                cur = [nxt]
        clusters.append(cur)

        clusters.sort(key=len, reverse=True)
        print(f"    clusters (gap<=32 B): {len(clusters)}")
        for c in clusters[:6]:
            lo_off = c[0][0]
            vals = [v for _, v in c]
            print(f"      @ {lo_off:#08x}  {len(c)} value(s): {vals[:10]}")
            # dump the raw bytes for manual reading
            print(f"        raw: {blob[lo_off:lo_off + min(32, len(c) * 2)].hex(' ')}")

        # most common value overall, as a sanity anchor
        cnt = Counter(v for _, v in hits)
        print(f"    most common: {cnt.most_common(5)}")

    print("\n" + "=" * 78)
    print("#  HOW TO READ THIS")
    print("=" * 78)
    print("  A cluster of several values in the 3.0-4.6 V range inside a structured")
    print("  register dump is a candidate for PMIC ADC output. It is a candidate, not")
    print("  a finding: the same range contains many unrelated 16-bit numbers.")
    print()
    print("  What would confirm it: the value moving between two dumps taken at")
    print("  different charge levels. That requires two captures, not more analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
