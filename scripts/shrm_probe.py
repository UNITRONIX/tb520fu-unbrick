#!/usr/bin/env python3
"""shrm_probe.py - examine the DDR bring-up module the programmer actually runs.

The pipeline, from the devprg's own strings
-------------------------------------------
    Entering DeviceProg DDR
    sbl1_load_ddr_training_data        <- training data is LOADED
    boot_pre_ddr_dtb_load              <- a DTB is loaded from storage
    sbl1_pmic_init
    boot_cdt_init
    sbl1_hw_platform_pre_ddr
    sbl1_hw_pre_ddr_init
    sbl1_ddr_set_params
    sbl1_ddr_init
    do_ddr_training
    sbl1_wait_for_ddr_training         <- this can block
    sbl1_post_ddr_init
    boot_post_ddr_dtb_load
    boot_ddr_share_data_to_aop
    boot_populate_ddr_details_shared_table

and separately:

    DDR_INIT with shrm.elf             <- training is delegated to a module
    boot_shrm_mini_dump_init
    shrm_load_cancel
    skip_ddr_init_in_EDL               <- a property that bypasses it
    sbl_error_handler FAIL: DDR not initialized
    sbl_error_handler: Unable to get DDR initialization state

The crash dump already showed us the other side of this: SHRM_MEM contains
'DDR_FW version : 102.6.0', the TRN_PRINT/TRN_ISSUE buffers and the full stage
list. So shrm.elf is the component doing the work, and it is image [4] of the
melf (the 148 924 B "DDR training" blob).

This extracts that image and reads what it needs - DCB, training data, PMIC,
frequency tables - so the failure can be aimed at rather than guessed.

Read-only, offline.

Usage
    python shrm_probe.py
    python shrm_probe.py --extract shrm.bin
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)

#: Image [4] starts here, per docs/04-melf-format.md
IMG4_OFF = 0x15AB48
IMG4_LEN = 148924

TERMS = [
    "ddr", "DDR", "dcb", "DCB", "shrm", "SHRM", "train", "Train",
    "freq", "Freq", "pll", "PLL", "lp5", "LP5", "lpddr", "LPDDR",
    "vref", "Vref", "vbat", "VBAT", "pmic", "PMIC",
    "fail", "Fail", "FAIL", "error", "Error", "assert", "Assert",
    "timeout", "Timeout", "abort", "Abort",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    ap.add_argument("--extract", default=None, help="write image [4] to this path")
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    b = path.read_bytes()

    if IMG4_OFF + IMG4_LEN > len(b):
        print(f"melf too short for image [4] at {IMG4_OFF:#x}")
        return 2
    img = b[IMG4_OFF:IMG4_OFF + IMG4_LEN]

    print("=" * 78)
    print("#  image [4] - the DDR / shrm module")
    print(f"#  {IMG4_OFF:#x}..{IMG4_OFF + IMG4_LEN:#x}  ({IMG4_LEN} B)")
    print("=" * 78)

    # ---- ELF header sanity ---------------------------------------------
    if img[:4] == b"\x7fELF":
        cls = img[4]
        machine = struct.unpack_from("<H", img, 18)[0]
        print(f"  ELF class={cls} machine={machine:#x}")
        if cls == 2:  # ELF64
            e_entry, e_phoff = struct.unpack_from("<QQ", img, 24)
            e_phnum = struct.unpack_from("<H", img, 56)[0]
            print(f"  entry={e_entry:#x} phoff={e_phoff:#x} phnum={e_phnum}")
            for i in range(e_phnum):
                o = e_phoff + i * 56
                if o + 56 > len(img):
                    break
                p_type, p_flags = struct.unpack_from("<II", img, o)
                p_off, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from(
                    "<QQQQQ", img, o + 8)
                if p_filesz:
                    print(f"    ph[{i}] type={p_type:#x} off={p_off:#x} "
                          f"vaddr={p_vaddr:#x} filesz={p_filesz:#x}")

    if args.extract:
        Path(args.extract).write_bytes(img)
        print(f"\n  written to {args.extract}")

    # ---- strings -------------------------------------------------------
    print(f"\n#  strings matching DDR / PMIC / failure terms")
    seen = set()
    for m in re.finditer(rb"[\x20-\x7e]{6,}", img):
        s = m.group().decode("ascii", "replace")
        if not any(t in s for t in TERMS):
            continue
        if s in seen:
            continue
        seen.add(s)
        print(f"  {IMG4_OFF + m.start():#08x}  {s[:116]}")

    print(f"\n  {len(seen)} distinct matching strings")

    # ---- does it carry its own DCB / training blobs? --------------------
    print("\n#  embedded blobs and version markers")
    for pat in (b"DCB", b"dcb", b"SHRM", b"shrm", b"TRN_PRINT", b"TRN_ISSUE",
                b"version", b"Version", b"VERSION"):
        i = img.find(pat)
        print(f"  {pat.decode():<12} {'@ ' + hex(IMG4_OFF + i) if i >= 0 else 'absent'}")

    print("\n" + "=" * 78)
    print("#  WHAT THIS MEANS FOR GETTING FIREHOSE UP")
    print("=" * 78)
    print("  The programming path never touches ABL. So the plan's premise -")
    print("  'only abl_a/abl_b are damaged' - cannot explain a Firehose hang.")
    print()
    print("  The sequence that must succeed is:")
    print("    PBL -> melf XBL -> load training data + pre-DDR DTB -> PMIC init")
    print("        -> CDS/DCB -> shrm.elf DDR training -> Firehose -> USB -> XML")
    print()
    print("  Observed failure: accepted, ~8 s of silence, watchdog at 7.918 s.")
    print("  That is consistent with blocking in sbl1_wait_for_ddr_training.")
    print()
    print("  Two concrete levers exist and are worth naming before testing:")
    print("    1. skip_ddr_init_in_EDL - a property the code consults. If DDR is")
    print("       already up (it is: the crashdump handler is running on it),")
    print("       reinitialising it may be both unnecessary and fatal.")
    print("    2. sbl1_load_ddr_training_data - training data comes from storage,")
    print("       not from computation. Its source partition can be read over the")
    print("       crash dump and verified without EDL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
