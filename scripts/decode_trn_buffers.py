#!/usr/bin/env python3
"""decode_trn_buffers.py - decide whether the last DDR training run PASSED.

The question this settles
-------------------------
SHRM_MEM contains the DDR firmware's stage list and its failure-reason table
(LE_RDQS_ALIGNMENT_FAIL, DCB_LOAD_FAIL, DRAM_DCC_FAIL, ...). Finding those proves
the *code* is resident. It says nothing about the outcome of the last run.

The distinction matters, because "the programmer dies in DDR bring-up" is
hypothesis 6.1 in docs/05-firehose-and-the-silence.md, and the whole case for a
test-point or a board swap rests on it. If training completed, that hypothesis
loses its footing.

How this decides it
-------------------
A failure produces a printed record through the format

    '%s: REASON=%s,FREQ=%s,CHANNEL=%s,CHIPSELECT=%s,BYTE=%s,BIT=%s,LIMIT=0x%X,VALUE=%d'

so a failed run must leave a record containing the literal 'REASON=' followed by
values, not format specifiers. Scanning for instantiated records is therefore a
direct test:

  * records found            -> training failed; parse them for the reason
  * only the format string   -> no failure was reported

The second case is only meaningful if the buffers are actually populated (a
buffer full of zeros proves nothing), so this script also reports occupancy and
looks for the ring-buffer structure around the TRN_PRINT / TRN_ISSUE labels.

Offline only.

Usage
    python decode_trn_buffers.py
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

DATA = Path(__file__).resolve().parent / "pmic_state_probe" / "SHRM_MEM.BIN"


def words(blob: bytes, start: int, count: int) -> str:
    out = []
    for i in range(count):
        off = start + i * 4
        if off + 4 > len(blob):
            break
        out.append(f"{struct.unpack_from('<I', blob, off)[0]:08x}")
    return " ".join(out)


def main() -> int:
    if not DATA.is_file():
        print(f"missing {DATA} - run pmic_state_probe.py first")
        return 2
    b = DATA.read_bytes()
    print("=" * 74)
    print(f"#  {DATA.name}  {len(b)} B  base 0x24020000")
    print("=" * 74)

    tp = b.find(b"TRN_PRINT")
    ti = b.find(b"TRN_ISSUE")
    print(f"\nTRN_PRINT label @ {tp:#x}   TRN_ISSUE label @ {ti:#x}")

    # ---- 1. structure around the labels --------------------------------
    print("\n# 32-bit words around the labels (looking for buffer pointers/lengths)")
    start = (tp - 32) & ~3
    for off in range(start, start + 160, 32):
        print(f"  {off:#06x}  {words(b, off, 8)}")

    # ---- 2. occupancy of each half -------------------------------------
    print("\n# occupancy (a buffer that is all zeros proves nothing)")
    half = len(b) // 2
    for name, lo, hi in (("lower half", 0, half), ("upper half", half, len(b))):
        seg = b[lo:hi]
        nz = sum(1 for x in seg if x)
        print(f"  {name:<12} {lo:#07x}..{hi:#07x}  nonzero {nz}/{len(seg)} ({nz/len(seg):.1%})")

    # ---- 3. the decisive test ------------------------------------------
    print("\n# instantiated failure records")
    fmt_only = 0
    real = []
    for m in re.finditer(rb"REASON=", b):
        off = m.start()
        tail = b[off:off + 256]
        # a format string has %s right after '='; a real record does not
        if tail[7:9] == b"%s":
            fmt_only += 1
            print(f"  {off:#07x}  FORMAT STRING (no values)")
        else:
            txt = tail.split(b"\x00")[0]
            real.append((off, txt))
            print(f"  {off:#07x}  RECORD: {txt[:150]!r}")
    print(f"\n  format strings: {fmt_only}")
    print(f"  real records  : {len(real)}")

    # ---- 4. any printed training text at all? ---------------------------
    print("\n# printable runs that look like training output (not the static tables)")
    static_region = b.find(b"UNCATEGORIZED")
    for m in re.finditer(rb"[\x20-\x7e]{10,}", b):
        s = m.group().decode("ascii", "replace")
        alpha = sum(c.isalpha() or c in " _:=-%.,()/" for c in s) / len(s)
        if alpha < 0.80:
            continue
        # skip the known static name tables and format string
        if s.startswith(("TRN_", "UNCATEGORIZED", "DDR_FW", "%s: REASON")):
            continue
        if s in ("INVALID_ECDT_ENTRY",):
            continue
        print(f"  {m.start():#07x}  {s[:100]!r}")

    # ---- verdict --------------------------------------------------------
    print("\n" + "=" * 74)
    print("#  VERDICT")
    print("=" * 74)
    if real:
        print("  Training DID report a failure. Reasons recorded above.")
        print("  => hypothesis 6.1 (programmer dies in DDR bring-up) gains support.")
    elif fmt_only:
        print("  The failure format exists but no instantiated record does.")
        print("  Read with the occupancy numbers above:")
        print("   - if the buffers are populated, this means the last training run")
        print("     finished without reporting a failure")
        print("   - if the buffers are empty, it proves nothing")
        print("  => treat 6.1 as UNSUPPORTED, not as disproven.")
    else:
        print("  No failure format and no records: inconclusive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
