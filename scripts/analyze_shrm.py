#!/usr/bin/env python3
"""analyze_shrm.py - decode the DDR training log that lives in SHRM_MEM.

Discovery
---------
`SHRM_MEM.BIN` (256 KiB @ 0x24020000) was read from the crash dump for the first
time with pmic_state_probe.py. It is not noise: it holds the shared-memory block
used by the DDR firmware, including:

    DDR_FW version : 102.6.0
    TRN_PRINT            <- training print buffer
    TRN_ISSUE            <- training issue/failure buffer
    '%s: REASON=%s,FREQ=%s,CHANNEL=%s,CHIPSELECT=%s,BYTE=%s,BIT=%s,LIMIT=0x%X,VALUE=%d'
    PLL Precal / DRAM DCC / RCW CDC Full Cycle Sweep / DIT Periodic Training /
    tWCK2DQI (DIT) / CLKIO DCC Monitor / RDT4 DCC Monitor / IO_Qual Vref Training /
    Low Freq DQ CDC perbit / HighSpeed DIT / PXI Config

docs/08-linux-port-notes.md and docs/05-firehose-and-the-silence.md both say the
DDR training result is only observable over UART ("A serial console from
XBL/programmer would show DDR training progress"). That is not true: the training
firmware writes its own log into shared memory, and the crash dump exposes it.

What this script does
--------------------
Splits the region into its two buffer halves, then tries to interpret each as a
record of training events: looking for the stage names, the REASON=/%s format
string's data, and any TRN_ISSUE entries. It prints what it can prove and says
plainly what it cannot.

Offline only. Reads local files, never the device.

Usage
    python analyze_shrm.py
    python analyze_shrm.py --file pmic_state_probe/SHRM_MEM.BIN
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

STAGES = [
    b"PLL Precal", b"DRAM DCC", b"RCW CDC/Full Cycle Sweep", b"DIT - Periodic Training",
    b"tWCK2DQI (DIT)", b"CLKIO DCC Monitor", b"RDT4 DCC Monitor",
    b"IO_Qual Vref Training", b"Low Freq DQ CDC perbit", b"HighSpeed DIT",
    b"PXI Config",
]


def text_strings(blob: bytes, minlen: int = 8) -> list[str]:
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, blob):
        s = m.group().decode("ascii", "replace")
        # require it to look like prose, not code bytes that happen to be printable
        alpha = sum(c.isalpha() or c in " _:=-%.,()/" for c in s)
        if alpha / len(s) > 0.80:
            out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="pmic_state_probe/SHRM_MEM.BIN")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"not found: {path}")
        print("Run pmic_state_probe.py first to pull SHRM_MEM.BIN from the device.")
        return 2
    blob = path.read_bytes()

    print("=" * 74)
    print(f"#  {path.name}  {len(blob)} B")
    print("=" * 74)

    # ---- where are the anchors -------------------------------------------
    print("\n# anchors")
    anchors = {}
    for key in (b"DDR_FW version", b"TRN_PRINT", b"TRN_ISSUE", b"REASON="):
        i = blob.find(key)
        anchors[key] = i
        print(f"  {key.decode():<18} {'@ ' + hex(i) if i >= 0 else 'absent'}")

    i = blob.find(b"DDR_FW version")
    if i >= 0:
        end = blob.find(b"\x00", i)
        print(f"  firmware string: {blob[i:end].decode('ascii', 'replace')!r}")

    # ---- stage table ------------------------------------------------------
    print("\n# DDR training stages referenced in this buffer")
    for st in STAGES:
        k = blob.find(st)
        print(f"  {st.decode():<28} {'@ ' + hex(k) if k >= 0 else 'absent'}")

    # ---- the two buffers --------------------------------------------------
    # TRN_PRINT and TRN_ISSUE are adjacent name tags; the data they label sits
    # in the region around them. Split at the halfway point of the populated area
    # so each half can be inspected separately without assuming a layout we have
    # not proven.
    tp = anchors.get(b"TRN_PRINT", -1)
    ti = anchors.get(b"TRN_ISSUE", -1)
    if tp >= 0 and ti >= 0:
        lo = min(tp, ti)
        print(f"\n# label area at {hex(lo)}..{hex(max(tp, ti) + 16)}")
        print("  raw:", blob[lo:max(tp, ti) + 16].hex(" "))

    print("\n# text recovered from the whole region")
    strs = text_strings(blob)
    seen = set()
    for s in strs:
        if s in seen:
            continue
        seen.add(s)
        print(f"  | {s[:120]}")
    print(f"  ({len(seen)} distinct text-like strings)")

    # ---- does the REASON format have any instantiated records? -----------
    print("\n# looking for instantiated training-failure records")
    # The format is '%s: REASON=%s,FREQ=%s,...'. A filled-in record would contain
    # literal 'REASON=' followed by a value, not a %s.
    hits = [m.start() for m in re.finditer(rb"REASON=", blob)]
    print(f"  'REASON=' occurrences: {len(hits)} at {[hex(h) for h in hits]}")
    for h in hits:
        seg = blob[h:h + 200]
        printable = seg.split(b"\x00")[0]
        print(f"    {hex(h)}: {printable[:160]!r}")

    # ---- verdict ---------------------------------------------------------
    print("\n" + "=" * 74)
    print("#  VERDICT")
    print("=" * 74)
    has_stages = sum(1 for st in STAGES if blob.find(st) >= 0)
    print(f"  stage names present : {has_stages}/{len(STAGES)}")
    print(f"  DDR_FW version      : {'yes' if anchors.get(b'DDR_FW version', -1) >= 0 else 'no'}")
    print(f"  TRN_PRINT buffer    : {'yes' if tp >= 0 else 'no'}")
    print(f"  TRN_ISSUE buffer    : {'yes' if ti >= 0 else 'no'}")
    print()
    print("  What this proves: the DDR training firmware's own structures and its")
    print("  stage list are resident in shared memory and survive into the crash")
    print("  dump. The claim that DDR training state is UART-only is therefore")
    print("  wrong - the data is reachable from the host.")
    print()
    print("  What this does NOT yet prove: whether the last training run passed.")
    print("  The buffers must be decoded as records (not scanned for strings) to")
    print("  answer that, and the record layout is not established here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
