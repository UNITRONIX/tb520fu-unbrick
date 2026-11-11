#!/usr/bin/env python3
"""parse_ddrdata_log.py - what the failed DDR_DATA attempt actually achieved.

The 29 MB log `ddrdata_log.txt` was recorded during an attempt to reach
DDR_DATA.BIN. docs/30-dump-order-blocks-ddr-data.md concluded from it that the
memory table is walked in ascending address order and stalls at 0x82800000,
so the highest-address region can never be reached.

This script tests that conclusion against the log rather than trusting it:

  * the order the regions were actually requested in,
  * how each read ended (real data / all 0xFF / all 0x00 / nothing),
  * which regions were reached before the run stopped,
  * whether DDR_DATA was ever requested.

Reading the log properly matters: it is UTF-16LE, so a naive read sees UTF-16
NUL bytes between characters and every regex silently matches nothing. That is
the same class of mistake as truncating a pipe - the tool answers, and the
answer is empty for a reason that has nothing to do with the device.

Usage
    python parse_ddrdata_log.py --log ../com_attempt/ddrdata_log.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

READ_RE = re.compile(
    r"Sent SAHARA_MEMORY_READ, address (0x[0-9a-fA-F]+), length (0x[0-9a-fA-F]+)")
HEAD_RE = re.compile(r"First few bytes: ([0-9A-Fa-f ]+)")
TABLE_RE = re.compile(r"Base (0x[0-9a-fA-F]+) Len (0x[0-9a-fA-F]+), '([^']+)', '([^']*)'")
RECV_RE = re.compile(r"Received: (\d+) bytes")


def kind(head: str | None) -> str:
    if not head:
        return "no-head"
    toks = head.split()
    if not toks:
        return "no-head"
    if all(t.upper() == "FF" for t in toks):
        return "all-FF"
    if all(t.upper() == "00" for t in toks):
        return "all-00"
    return "REAL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    # UTF-16LE - a plain text read yields nothing and every regex comes back empty.
    with open(args.log, "r", encoding="utf-16", errors="replace") as f:
        text = f.read()
    lines = text.splitlines()
    print(f"log: {len(lines)} lines, {len(text)} chars")

    # ---- the table as the device declared it ----------------------------
    table = []
    for line in lines:
        m = TABLE_RE.search(line)
        if m:
            table.append({"addr": int(m.group(1), 16), "len": int(m.group(2), 16),
                          "file": m.group(3), "desc": m.group(4)})
    print(f"\ntable entries declared: {len(table)}")

    # ---- the order actually used ----------------------------------------
    reads = []
    for i, line in enumerate(lines):
        m = READ_RE.search(line)
        if not m:
            continue
        addr, length = int(m.group(1), 16), int(m.group(2), 16)
        head = None
        for j in range(i + 1, min(i + 14, len(lines))):
            hm = HEAD_RE.search(lines[j])
            if hm:
                head = hm.group(1).strip()
                break
        reads.append((addr, length, head))
    print(f"reads issued: {len(reads)}")
    if not reads:
        print("no reads parsed - check the encoding")
        return 1

    # ---- order ----------------------------------------------------------
    asc = all(reads[i][0] <= reads[i + 1][0] for i in range(len(reads) - 1))
    desc = all(reads[i][0] >= reads[i + 1][0] for i in range(len(reads) - 1))
    print(f"\nstrictly ascending by address? {asc}")
    print(f"strictly descending by address? {desc}")
    if not asc and not desc:
        print("neither - the order is not a simple address sort")
        print("first 12 addresses:")
        for a, ln, _ in reads[:12]:
            print(f"  0x{a:011x} len=0x{ln:x}")

    # ---- outcomes -------------------------------------------------------
    counts = Counter(kind(h) for _, _, h in reads)
    print("\noutcomes across all reads:")
    for k, v in counts.most_common():
        print(f"  {k:<10} {v:>6}")

    # ---- coverage per declared region -----------------------------------
    print("\nper-region coverage (first MiB-granular run containing it):")
    reached: dict[str, str] = {}
    for e in table:
        first = next((h for a, _, h in reads if a == e["addr"]), None)
        if first is None:
            reached[e["file"]] = "never requested"
        else:
            reached[e["file"]] = kind(first)

    for e in table:
        status = reached[e["file"]]
        big = e["len"] >= 0x1000000
        if big or status != "never requested":
            print(f"  {e['file']:<20} 0x{e['addr']:011x} {e['len'] / 2**20:8.0f} MiB  {status}")

    # ---- the specific question ------------------------------------------
    print("\n" + "=" * 68)
    ddr = next((e for e in table if e["file"].startswith("DDR_DATA")), None)
    if ddr:
        print(f"DDR_DATA declared at 0x{ddr['addr']:x} len 0x{ddr['len']:x}")
        print(f"DDR_DATA ever requested: "
              f"{any(a == ddr['addr'] for a, _, _ in reads)}")
    cs0 = next((e for e in table if e["file"].startswith("DDRCS0_0")), None)
    if cs0:
        got = [a for a, _, _ in reads if cs0["addr"] <= a < cs0["addr"] + cs0["len"]]
        print(f"DDRCS0_0 reads: {len(got)}"
              f"  (declared {cs0['len'] / 2**30:.0f} GiB)")
    hi = [a for a, _, _ in reads if a >= 0x980000000]
    if hi:
        print(f"reads at or above 0x980000000: {len(hi)}"
              f"   highest 0x{max(hi):011x}")
        print("  -> memory far above the alleged 40 MiB wall WAS requested and answered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
