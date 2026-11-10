#!/usr/bin/env python3
"""check_skip_prop.py - is skip_ddr_init_in_EDL actually set on this board?

Why this decides something
--------------------------
disasm_around.py recovered the logic that consumes the property:

    0x14831244  adrp x1, ...            name
    0x14831248  add  x0, sp, #0x8       node handle
    0x1483124c  add  x1, x1, #0x619     "skip_ddr_init_in_EDL"
    0x14831250  add  x2, sp, #0x4       &value
    0x14831254  bl   0x1484ec14         get_property(node, name, &value)
    0x14831258  cbnz w0, 0x148312c4     lookup failed -> different path
    0x1483125c  ldr  w8, [sp, #0x4]     value
    0x148312a8  cbz  w8, 0x148312d0     value == 0 -> SKIP DDR INIT

So the property is a device-tree property, and a value of **0** takes the branch
that skips DDR initialisation.

That makes one question answerable entirely offline: does this board's device tree
declare the property, and with what value? If it is absent, the `cbnz` on the
lookup error is taken and DDR init runs - which is what we observe. If it were
present with value 0, DDR init would be skipped and the programmer would not hang
in training.

This checks every device tree we hold, and reports presence and value.

Read-only, offline.

Usage
    python check_skip_prop.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decode_fdt import Fdt  # noqa: E402

PAYLOADS = Path(__file__).resolve().parent / "xbl_config_payloads"
TARGET = "skip_ddr_init_in_EDL"

#: Where else the property could legitimately live, for context.
RELATED = ["ddr_log_level", "ddr_boot_freq", "ddr_trng_always_en",
           "ddr_tr_led_flag", "extnd_term_log_flag"]


def main() -> int:
    print("=" * 78)
    print(f'#  is "{TARGET}" present, and with what value?')
    print("=" * 78)

    found_any = False
    for name in ("A00C_8_0200_1_dcb.bin", "pre-ddr-lanai-1.0.dtb"):
        f = PAYLOADS / name
        if not f.is_file():
            print(f"\n  {name}: missing (run extract_xbl_config.py)")
            continue
        d = Fdt(f.read_bytes())
        props = list(d.walk())
        print(f"\n  {name}: {len(props)} properties")

        target = [(p, n, v) for p, n, v in props if n == TARGET]
        if target:
            for p, n, v in target:
                val = int.from_bytes(v, "big") if v else None
                print(f"    PRESENT at /{p}")
                print(f"      raw   = {v.hex(' ')}")
                print(f"      value = {val}")
                print(f"      -> DDR init {'SKIPPED (0)' if val == 0 else 'RUNS (non-zero)'}")
            found_any = True
        else:
            print(f"    ABSENT - no node declares {TARGET}")

        # related flags, for the picture of what IS configured
        print("    related DDR flags:")
        for key in RELATED:
            hits = [(p, v) for p, n, v in props if n == key]
            if hits:
                for p, v in hits:
                    val = int.from_bytes(v, "big") if v else None
                    print(f"      /{p}:{key} = {val}")
            else:
                print(f"      {key}: absent")

        # is a UEFI/EDL conditional property present at all?
        edl = [(p, n) for p, n, _ in props if "edl" in n.lower()]
        print(f"    properties mentioning 'edl': {len(edl)}")
        for p, n in edl[:10]:
            print(f"      /{p}:{n}")

    print("\n" + "=" * 78)
    print("#  CONCLUSION")
    print("=" * 78)
    if found_any:
        print("  The property is declared. Check the value above: 0 means DDR init")
        print("  is skipped, non-zero means it runs. If it is declared 0 here and")
        print("  DDR init still runs, some other condition overrides it.")
    else:
        print("  The property is NOT declared in either device tree we hold.")
        print()
        print("  That is consistent with the observed behaviour: the lookup at")
        print("  0x14831254 fails, the `cbnz` at 0x14831258 is taken, and the")
        print("  code proceeds to initialise DDR - which is the step after which")
        print("  the programmer never speaks again.")
        print()
        print("  It also means the bypass is available in principle but unused,")
        print("  because nothing supplies it. Declaring it would require writing")
        print("  a device tree the boot chain reads - i.e. the write access that")
        print("  is the original blocker. So this is a real lever, but not one we")
        print("  can pull from the host today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
