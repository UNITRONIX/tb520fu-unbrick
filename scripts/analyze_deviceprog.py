#!/usr/bin/env python3
"""analyze_deviceprog.py - what does the devprg XBL actually do at startup?

The contradiction this addresses
--------------------------------
The whole recovery plan rests on one claim: "only abl_a and abl_b are damaged;
hardware and everything below the bootloader are fine" (docs/09-service-report.md).

But the EDL path never executes ABL. PBL loads the melf, the melf runs its own
XBL core in RAM, that XBL brings up DDR, then the Firehose programmer runs.
ABL is a partition on UFS and plays no part in it.

So if the programmer hangs, "only ABL is broken" cannot be the explanation. Either
the claim is incomplete, or the hang is caused by something the devprg XBL
reads - which is reachable and checkable.

This extracts the devprg's own boot sequence from its string table, so the work
can target a real step instead of a hypothesis.

Read-only, offline.

Usage
    python analyze_deviceprog.py
    python analyze_deviceprog.py --melf <path>
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)

#: Anchors that mark the phases we care about, in expected execution order.
PHASES = [
    (b"Entering DeviceProg", "devprg entry"),
    (b"sbl1_ddr_init", "SBL-style DDR init"),
    (b"do_ddr_training", "DDR training"),
    (b"DCB", "DCB (DDR config block)"),
    (b"loader-dbc", "Dynamic Battery Check"),
    (b"vsys-min-recover-mv", "VSYS recovery threshold"),
    (b"vbatt-min", "VBATT threshold"),
    (b"battery-low-threshold-mv", "battery low threshold"),
    (b"charger is not charging", "charger detection failure"),
    (b"battery recover failed", "battery recovery failure"),
    (b"UFS", "UFS"),
    (b"firehose", "Firehose"),
]

#: Anything containing these is worth printing verbatim.
KEYWORDS = [
    "ddr", "DDR", "dcb", "DCB", "train", "Train", "pll", "PLL",
    "vbat", "VBAT", "vsys", "VSYS", "charger", "Charger", "battery", "Battery",
    "ufs", "UFS", "firehose", "Firehose", "xml", "XML", "usb", "USB",
    "fatal", "FATAL", "assert", "Assert", "error", "Error", "fail", "Fail",
    "shutdown", "Shutdown", "reset", "Reset", "prog", "Prog",
]


def strings_in(blob: bytes, minlen: int = 6) -> list[tuple[int, str]]:
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, blob):
        s = m.group().decode("ascii", "replace")
        alpha = sum(c.isalpha() or c in " _:=-%.,()/[]<>" for c in s)
        if alpha / len(s) > 0.80:
            out.append((m.start(), s))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        print(f"melf not found: {path}")
        return 2
    b = path.read_bytes()

    print("=" * 78)
    print(f"#  {path.name}  {len(b)} B")
    print("=" * 78)

    # ---- 1. which phase anchors exist, and where ------------------------
    print("\n#  phase anchors (presence is not proof of execution order)")
    for pat, label in PHASES:
        i = b.find(pat)
        print(f"  {label:<28} {'@ ' + hex(i) if i >= 0 else 'absent'}")

    # ---- 2. the DeviceProg neighbourhood -------------------------------
    i = b.find(b"Entering DeviceProg")
    if i < 0:
        i = b.find(b"DeviceProg")
    if i >= 0:
        print(f"\n#  strings around the devprg entry point (from {i:#x})")
        for off, s in strings_in(b[i - 400:i + 3000]):
            print(f"  {i - 400 + off:#08x}  {s[:120]}")

    # ---- 3. DDR / DCB / power strings, grouped -------------------------
    print("\n#  DDR / DCB / power-management strings")
    all_strs = strings_in(b, 8)
    groups = {
        "DDR": ["ddr", "DDR", "train", "Train", "pll", "PLL", "dcb", "DCB"],
        "POWER": ["vbat", "VBAT", "vsys", "VSYS", "charger", "battery", "shutdown"],
        "STORAGE": ["ufs", "UFS", "storage"],
    }
    for gname, keys in groups.items():
        hits = [(o, s) for o, s in all_strs if any(k in s for k in keys)]
        print(f"\n  --- {gname}: {len(hits)} strings")
        for o, s in hits[:40]:
            print(f"    {o:#08x}  {s[:120]}")
        if len(hits) > 40:
            print(f"    ... {len(hits) - 40} more")

    # ---- 4. does the devprg XBL contain a UFS driver? ------------------
    print("\n#  evidence for / against a working UFS stack inside the devprg")
    ufs = [s for _, s in all_strs if "ufs" in s.lower()]
    print(f"  UFS-mentioning strings: {len(ufs)}")
    for s in ufs[:15]:
        print(f"    {s[:110]}")

    print("\n" + "=" * 78)
    print("#  READING")
    print("=" * 78)
    print("  The EDL path does not involve ABL. If the devprg reaches DDR and UFS")
    print("  stages, then a broken ABL cannot explain a Firehose hang, and the")
    print("  'only abl_a/abl_b are damaged' claim must be narrowed or dropped.")
    print("  What the devprg reads at runtime - DCB, VBAT, UFS - is the real list")
    print("  of suspects.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
