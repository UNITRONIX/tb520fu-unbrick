#!/usr/bin/env python3
"""ddr_pipeline.py - full extract of the devprg DDR bring-up path.

Why this is the core question
-----------------------------
The EDL path does not use ABL. PBL loads the melf, the melf runs its own XBL in
RAM, that XBL brings DDR up, then Firehose runs. So "only abl_a/abl_b are damaged"
cannot explain the hang.

The strings inside the devprg name the actual steps, and two of them are new and
important:

    sbl1_load_ddr_training_data      the training data is LOADED, not computed
    DDR_INIT with shrm.elf           a separate firmware performs the training
    skip_ddr_init_in_EDL             a flag exists to bypass DDR init in EDL
    CDT not found in any storage media, using defaults
    Error: Platform ID is not programmed

If training data is loaded from storage and storage cannot be read, DDR never
comes up - and the programmer dies before it can raise USB. That is a mechanism,
not a guess.

This script dumps every string in the devprg that participates in that pipeline,
in address order, so the sequence can be read as a whole.

Read-only, offline.

Usage
    python ddr_pipeline.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)

#: Ordered list of the pipeline stages, by the string that names each one.
PIPELINE = [
    ("devprg entry", b"Entering DeviceProg"),
    ("load training data", b"sbl1_load_ddr_training_data"),
    ("pre-DDR DTB", b"boot_pre_ddr_dtb_load"),
    ("platform pre-DDR", b"sbl1_hw_platform_pre_ddr"),
    ("hw pre-DDR init", b"sbl1_hw_pre_ddr_init"),
    ("set DDR params", b"sbl1_ddr_set_params"),
    ("ddr_init", b"sbl1_ddr_init"),
    ("training", b"do_ddr_training"),
    ("wait training", b"sbl1_wait_for_ddr_training"),
    ("post ddr init", b"sbl1_post_ddr_init"),
    ("post-DDR DTB", b"boot_post_ddr_dtb_load"),
    ("share to AOP", b"boot_ddr_share_data_to_aop"),
    ("populate smem table", b"boot_populate_ddr_details_shared_table"),
]

#: Any string containing one of these belongs to the DDR/power pipeline.
TERMS = [
    "cdt", "CDT", "dcb", "DCB", "ddr", "DDR", "shrm", "SHRM",
    "training", "Training", "vbat", "VBAT", "vsys", "VSYS",
    "platform_id", "Platform ID", "pmic", "PMIC",
]


def strings_in(blob: bytes, lo: int, hi: int, minlen: int = 8):
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, blob[lo:hi]):
        s = m.group().decode("ascii", "replace")
        a = sum(c.isalpha() or c in " _:=-%.,()/[]<>+*" for c in s)
        if a / len(s) > 0.78:
            out.append((lo + m.start(), s))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    b = path.read_bytes()

    print("=" * 78)
    print("#  devprg DDR bring-up pipeline")
    print(f"#  {path.name}  {len(b)} B")
    print("=" * 78)

    print("\n#  ordered stages (string presence + offset)")
    for label, pat in PIPELINE:
        i = b.find(pat)
        print(f"  {label:<24} {'@ ' + hex(i) if i >= 0 else 'ABSENT'}")

    # The whole string blob for the DDR/power area sits roughly 0xb9000..0xc1000.
    lo, hi = 0xB9000, 0xC2000
    print(f"\n#  every DDR / power string in {lo:#x}..{hi:#x} (address order)")
    strs = strings_in(b, lo, hi)
    hits = [(o, s) for o, s in strs if any(t in s for t in TERMS)]
    print(f"   {len(hits)} matching strings\n")
    for o, s in hits:
        print(f"  {o:#08x}  {s[:118]}")

    # ---- the flag that can skip DDR init in EDL ------------------------
    print("\n" + "=" * 78)
    print("#  skip_ddr_init_in_EDL")
    print("=" * 78)
    i = b.find(b"skip_ddr_init_in_EDL")
    if i < 0:
        print("  string absent")
    else:
        print(f"  string @ {i:#x}")
        for o, s in strings_in(b, i - 200, i + 300, 6):
            print(f"    {o:#08x}  {s[:110]}")
        print()
        print("  This is a property name, so it is read from a device tree or")
        print("  from SMEM. If it can be set, DDR init is skipped in EDL and the")
        print("  programmer proceeds without training - which is exactly the step")
        print("  that may be failing. Finding its consumer is the next task.")

    # ---- CDT / platform id ---------------------------------------------
    print("\n" + "=" * 78)
    print("#  CDT and platform id")
    print("=" * 78)
    for pat in (b"CDT not found", b"Platform ID is not programmed", b"boot_cdt"):
        j = b.find(pat)
        print(f"  {pat.decode():<40} {'@ ' + hex(j) if j >= 0 else 'absent'}")
    print()
    print("  'CDT not found ... using defaults' is recoverable. 'Platform ID is")
    print("  not programmed' is a hard error string - worth checking whether it")
    print("  is reached before or after DDR.")

    print("\n" + "=" * 78)
    print("#  NEXT")
    print("=" * 78)
    print("  1. Find what consumes skip_ddr_init_in_EDL (DT property vs SMEM key).")
    print("  2. Find where sbl1_load_ddr_training_data reads from (UFS partition?).")
    print("  3. If it reads a partition, that partition is readable over the crash")
    print("     dump - so the data can be verified from the host without EDL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
