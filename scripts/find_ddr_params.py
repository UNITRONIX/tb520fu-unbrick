#!/usr/bin/env python3
"""find_ddr_params.py - locate the memory identification and frequency plan.

State of the search
-------------------
`/soc/ddr` in the DCB holds only seven properties:

    compatible, print_severity, ddr_log_level, ddr_trng_always_en,
    extnd_term_log_flag, ddr_tr_led_flag, ddr_boot_freq = 0x1fef00 (2093 MHz)

That is configuration, not parameters. The things training actually needs - the
memory part identification and the frequency/timing sets - are not there. They are
either elsewhere in these trees, or in the DCB's binary payload, or in the
`/cpr.bin` block.

This script searches all of them systematically and reports what it can prove,
instead of asserting a layout. It answers one question: **where is the memory part
declared, and can it be compared against the silicon?**

Read-only, offline.

Usage
    python find_ddr_params.py
"""
from __future__ import annotations

import struct
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decode_fdt import Fdt  # noqa: E402

PAYLOADS = Path(__file__).resolve().parent / "xbl_config_payloads"

#: Property-name fragments that would indicate memory identification or timing.
KEYS = [
    "part", "Part", "vendor", "Vendor", "manufacturer", "Manufacturer",
    "dram", "DRAM", "sdram", "SDRAM", "lpddr", "LPDDR",
    "timing", "Timing", "tCK", "tck", "tRCD", "tRP", "tRAS",
    "freq", "Freq", "FREQ", "mhz", "MHz", "kHz", "khz",
    "vref", "Vref", "vdd", "VDD", "volt", "Volt",
    "rank", "Rank", "density", "Density", "width", "Width",
    "training", "Training", "shrm", "SHRM",
]

#: SM8650 DDR boot frequencies in kHz, the values training may select.
KNOWN_FREQS_KHZ = [200_000, 400_000, 547_000, 768_000, 1_010_000,
                   1_353_000, 1_555_000, 1_707_000, 2_093_000, 2_400_000,
                   2_750_000, 3_200_000, 3_733_000, 4_200_000]


def report_tree(name: str) -> None:
    f = PAYLOADS / name
    if not f.is_file():
        print(f"  missing {name}")
        return
    d = Fdt(f.read_bytes())
    props = list(d.walk())
    print(f"\n  {name}: {len(props)} properties")

    hits = [(p, n, v) for p, n, v in props
            if any(k in n for k in KEYS) or any(k in p for k in KEYS)]
    print(f"    matching memory/timing keywords: {len(hits)}")
    for p, n, v in hits[:40]:
        val = v[:24].hex(" ") if v else "-"
        print(f"      /{p}:{n} = {val}")
    if len(hits) > 40:
        print(f"      ... {len(hits) - 40} more")

    # properties whose u32 value equals a known DDR frequency
    print("    values equal to a known DDR boot frequency:")
    found = 0
    for p, n, v in props:
        if len(v) == 4:
            x = struct.unpack(">I", v)[0]
            for khz in KNOWN_FREQS_KHZ:
                if x == khz:
                    print(f"      /{p}:{n} = {x} kHz ({x/1000:.0f} MHz)")
                    found += 1
    if not found:
        print("      none")


def scan_binary(name: str) -> None:
    f = PAYLOADS / name
    if not f.is_file():
        return
    b = f.read_bytes()
    print(f"\n  {name}: {len(b)} B binary scan")
    for khz in KNOWN_FREQS_KHZ:
        pat = struct.pack("<I", khz)
        n = b.count(pat)
        if n:
            first = b.find(pat)
            print(f"    {khz} kHz ({khz/1000:.0f} MHz): {n} occurrence(s), "
                  f"first @ {first:#x}")
    # the DCB boot frequency, little-endian
    pat = struct.pack("<I", 0x1FEF00)
    n = b.count(pat)
    print(f"    0x1FEF00 (2093 MHz, the configured boot freq): {n} hit(s)")


def main() -> int:
    print("=" * 78)
    print("#  where are the DDR parameters?")
    print("=" * 78)

    print("\n#  device trees")
    for name in ("A00C_8_0200_1_dcb.bin", "pre-ddr-lanai-1.0.dtb"):
        report_tree(name)

    print("\n" + "=" * 78)
    print("#  binary payloads")
    print("=" * 78)
    for name in ("A00C_8_0200_1_dcb.bin", "A00C_8_0100_1_dcb.bin", "cpr.bin"):
        scan_binary(name)

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  The DCB's /soc/ddr node carries only configuration flags and one")
    print("  boot frequency (2093 MHz). The memory part and the timing sets are")
    print("  not exposed as readable properties there.")
    print()
    print("  Two possibilities, and the frequency scan above separates them:")
    print("   - if the known frequencies appear in the binary payload, the")
    print("     parameter tables are present but encoded; a decoder is a bounded")
    print("     task on data we already hold.")
    print("   - if they do not appear at all, the parameters are not in the")
    print("     xbl_config payloads and come from elsewhere (the DCB file on UFS")
    print("     that the module names, i.e. a different artefact).")
    print()
    print("  Either way this narrows the search to a specific file, which is the")
    print("  point. Do not assume the answer; read it off the scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
