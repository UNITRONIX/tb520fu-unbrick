"""cold_boot_check.py - the gate for the cold-boot experiment, decided from the boot log.

Why this exists
---------------
`docs/59` and `docs/61` reduce the whole EDL decision to one variable:

    dload_entry_count at 0x148F0080   (ldrh, compared against 2)

It increments on every entry into `boot_dload_entry`, the block it lives in is preserved
across a warm reset and re-initialised by a genuine cold boot, and the one boot that
reached EDL did so **without** logging the `> 1` message - i.e. it was a first entry.

`docs/59` s6 therefore gives the next test, and it is cheap:

    1. leave the tablet fully off, no cable, long enough for the block to re-initialise
    2. power on ONCE
    3. do not warm-reset it
    4. read the XBL log for "boot_dload_entry" and for the ABSENCE of the counter message

Step 4 is what this script does. The XBL log is a text ring in the crash-dump capture -
`docs/56` found it at 0x81CE0000, and the format is `B - <usec> - <message>`. So instead
of guessing whether the cold boot worked, the log itself can be read for the three lines
that decide it.

What it can and cannot decide
-----------------------------
It can answer: did this boot reach `boot_dload_entry`? Was the counter message absent?
It cannot answer: what the counter's value is - the address is outside every region the
crash handler maps (`docs/62`). The log is the proxy, and it is a good one because the
code logs exactly when the comparison fails.

Usage
    python cold_boot_check.py --dump com_attempt/DDRCS0_0_first40MB.bin
    python cold_boot_check.py --dump <file> --grep
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# The three lines docs/58 s1 and docs/59 s6 say to look for.
MARKERS = {
    "tcrs": re.compile(rb"TCSR reg value\s+0x([0-9a-fA-F]+)"),
    "ramdump": re.compile(rb"RamDump -\s+Image Loaded, Delta -\s+\(?(\d+)\s*Bytes"),
    "dload": re.compile(rb"boot_dload_entry"),
    "count_warn": re.compile(rb"dload_entry_count\s*>\s*1"),
}

LOG_START = re.compile(rb"Format: Log Type - Time\(microsec\)")


def find_logs(buf: bytes) -> list[tuple[int, int]]:
    """Every XBL log ring in the capture, as (start, end).

    Plural on purpose. docs/58 compared TWO logs inside one dump - a warm-reset boot at
    0x81A00000 and a shutdown boot at 0x81CE4000 - and the whole finding (one reached
    `boot_dload_entry`, the other did not) rests on that pair. A scanner that returns
    only the first header sees one log, reports a verdict, and silently hides the other
    half of the evidence.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        m = LOG_START.search(buf, pos)
        if not m:
            break
        start = m.start()
        # The ring is text; the written area ends at a long NUL run.
        tail_limit = min(len(buf), start + (1 << 20))
        end = tail_limit
        n = buf.find(b"\x00" * 64, start, tail_limit)
        if n > start + 200:
            end = n
        spans.append((start, end))
        pos = end if end > start else start + 1
    return spans


def find_log(buf: bytes) -> tuple[int, int] | None:
    spans = find_logs(buf)
    return spans[0] if spans else None


def analyse(path: Path) -> int:
    if not path.is_file():
        print(f"no such file: {path}")
        return 2
    buf = path.read_bytes()
    print(f"{path.name}: {len(buf)} B")

    spans = find_logs(buf)
    if not spans:
        print("  no XBL log header found ('Format: Log Type - Time(microsec)')")
        print("  -> this capture does not contain the boot log; try another dump")
        return 1

    print(f"  {len(spans)} XBL log(s) found - docs/58 s1 compared two, so both matter")
    rc = 1
    best = None
    for idx, (start, end) in enumerate(spans):
        log = buf[start:end]
        found: dict[str, str] = {}
        for name, rx in MARKERS.items():
            m = rx.search(log)
            if name == "tcrs" and m:
                found[name] = f"0x{m.group(1).decode()}"
            elif name == "ramdump" and m:
                found[name] = f"{m.group(1).decode()} B"
            elif m:
                found[name] = "present"
            else:
                found[name] = "-"

        print()
        print(f"  --- log {idx + 1} at {start:#x} ({len(log)} B) ---")
        print(f"  {'TCSR reg value':22s} {found['tcrs']}")
        print(f"  {'RamDump loaded':22s} {found['ramdump']}")
        print(f"  {'boot_dload_entry':22s} {found['dload']}")
        print(f"  {'counter > 1 warn':22s} {found['count_warn']}")

        reached = found["dload"] != "-"
        warned = found["count_warn"] != "-"
        loaded = found["ramdump"] not in ("-", "0 B")
        if reached and not warned and loaded:
            verdict = ("FIRST-ENTRY PATH: boot_dload_entry reached, no counter warning - "
                       "this boot should offer 9008 with a fresh HELLO")
            best = (idx, verdict)
            rc = 0
        elif reached and warned:
            verdict = ("download path taken BUT the counter warned - not a first entry, "
                       "so the config block was not re-initialised")
        elif not reached:
            verdict = ("crashdump path - boot_dload_entry not reached, so no 9008 by "
                       "design (docs/58)")
        else:
            verdict = "unclassified"
        print(f"    {verdict}")

    print()
    if best:
        print(f"  VERDICT: log {best[0] + 1} took the first-entry path. That is the boot")
        print("           profile that produces 9008 with a fresh HELLO.")
    else:
        print("  VERDICT: no log in this capture shows a first-entry download boot.")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=None, help="a RAM capture containing the XBL log")
    ap.add_argument("--grep", action="store_true", help="print matching log lines")
    args = ap.parse_args()

    if args.dump:
        return analyse(Path(args.dump))

    # No argument: look for the captures this repository already has.
    candidates = [
        REPO / "com_attempt" / "DDRCS0_0_first40MB.bin",
        REPO / "com_attempt" / "real_content" / "DDRCS0_0_first28MB.bin",
    ]
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        print("no capture given and none of the known ones exist:")
        for p in candidates:
            print(f"  {p}")
        return 2
    rc = 0
    for p in existing:
        rc |= analyse(p)
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
