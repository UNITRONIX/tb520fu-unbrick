#!/usr/bin/env python3
"""find_changing_bytes.py - which bytes in PMIC_BLOCK actually move between boots?

The lead
--------
live_probe.py found two regions whose hash differs between two captures taken 40 s
apart:

    PMIC_BLOCK   0x81B75000 .. 0x81B76000     CHANGED
    OCIMEM_HEAD  0x14680000 .. 0x14682000     CHANGED
    SHRM_HEAD    0x24020000 .. 0x24022000     identical

while every scalar register (RST_STAT, PMIC_PON, FSM_STS, FSM_CTRL, DBG_EN) was
identical and PMON_HIS was byte-for-byte the same both times.

That pattern is informative: the boot failure is deterministic, but something in the
PMIC block and in OCIMEM carries per-boot state. A monotonically increasing counter
would explain it trivially; a changing *register* would be a lead.

This takes several captures and reports, byte by byte, exactly which offsets move and
in what way. Offsets that increase are counters. Offsets that change non-monotonically
are state.

Read-only. One MEMORY_DEBUG session per capture.

Usage
    python find_changing_bytes.py
    python find_changing_bytes.py --samples 4 --delay 25
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import (  # noqa: E402
    close_session,
    handshake_memory_debug,
    mem_read,
    open_device,
)

OUT = Path(__file__).resolve().parent / "changing_bytes"
T0 = time.time()

REGIONS = [
    (0x81B75000, 0x1000, "PMIC_BLOCK"),
    (0x14680000, 0x1000, "OCIMEM_HEAD"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def capture(budget: float = 100.0) -> dict | None:
    end = time.time() + budget
    link = tables = None
    while time.time() < end:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception:  # noqa: BLE001
            link = tables = None
        if tables:
            break
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        end2 = time.time() + 70
        while time.time() < end2 and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.05)
    if not tables:
        return None

    out = {}
    for addr, ln, name in REGIONS:
        blob = mem_read(link, addr, ln, tmo=8.0)
        if blob:
            out[name] = blob

    # Close as soon as the reads are done, rather than relying on process exit.
    # An outstanding read that is abandoned is the state that leaves the node mute.
    close_session(link)
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--delay", type=float, default=25.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    print("=" * 74)
    print(f"#  byte-level change detection, {args.samples} samples")
    print("=" * 74)

    samples = []
    for i in range(args.samples):
        log(f"sample {i + 1}/{args.samples}")
        s = capture()
        if s is None:
            log("  no session")
            continue
        samples.append(s)
        for name, blob in s.items():
            (OUT / f"s{i}_{name}.bin").write_bytes(blob)
        if i + 1 < args.samples:
            time.sleep(args.delay)

    if len(samples) < 2:
        log("need at least two samples")
        return 1

    for addr, ln, name in REGIONS:
        blobs = [s[name] for s in samples if name in s]
        if len(blobs) < 2:
            continue
        n = min(len(b) for b in blobs)
        print()
        print("=" * 74)
        print(f"#  {name}  ({len(blobs)} samples, {n} bytes each)")
        print("=" * 74)

        diffs = []
        for off in range(n):
            vals = [b[off] for b in blobs]
            if len(set(vals)) > 1:
                diffs.append((off, vals))

        if not diffs:
            print("  no byte differs across samples")
            continue

        print(f"  {len(diffs)} byte(s) differ")
        # group into runs
        runs = []
        cur = [diffs[0]]
        for prev, nxt in zip(diffs, diffs[1:]):
            if nxt[0] - prev[0] <= 4:
                cur.append(nxt)
            else:
                runs.append(cur)
                cur = [nxt]
        runs.append(cur)

        print(f"  {len(runs)} contiguous run(s)")
        for run in runs[:25]:
            lo = run[0][0]
            hi = run[-1][0]
            print(f"\n    offset {lo:#06x}..{hi:#06x}  ({len(run)} byte(s))")
            # show as u32 where possible
            if lo % 4 == 0 and hi - lo < 16:
                for k in range(0, (hi - lo + 4) // 4 * 4, 4):
                    if lo + k + 4 > n:
                        break
                    words = []
                    for b in blobs:
                        words.append(struct.unpack_from("<I", b, lo + k)[0])
                    mono = all(words[j] <= words[j + 1] for j in range(len(words) - 1))
                    tag = "counter-like" if mono and len(set(words)) > 1 else ""
                    print(f"      +{k}: " + " -> ".join(hex(w) for w in words)
                          + (f"   {tag}" if tag else ""))
            else:
                for b_idx, off, vals in [(0, run[0][0], run[0][1])]:
                    print(f"      first byte: " + " -> ".join(hex(v) for v in vals))

    print()
    print("=" * 74)
    print("#  HOW TO READ THIS")
    print("=" * 74)
    print("  A value that increases monotonically across samples is a counter -")
    print("  useful only for confirming the boot really is recurring.")
    print("  A value that changes non-monotonically, or a register that toggles, is")
    print("  live state and is where the interesting information is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
