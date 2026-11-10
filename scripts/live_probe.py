#!/usr/bin/env python3
"""live_probe.py - use the connected tablet to test the silent-failure hypothesis.

The hypothesis
--------------
docs/20-entry-point-spin.md establishes that the programmer's `main` accumulates an
error code and returns, and that the entry code falls straight into `b .` without
checking it. A total failure would therefore look identical to a clean shutdown.

If that is what happens, the device should have produced something observable *after*
the attempt: a reset cause, and possibly state left in memory. The crash dump is the
only window onto that, and the device answers it right now.

What this session collects
--------------------------
  1. whether the node is responsive (or a zombie needing a power cycle)
  2. the full memory table, to confirm the handler is healthy
  3. RST_STAT / PMIC_PON / FSM_STS / DBG_EN - the reset picture
  4. PMON_HIS, decoded as PLOG records, which records a history of power events
  5. any region whose content differs from a baseline captured minutes ago

Point 5 is the interesting one: if the device runs the same failing sequence on every
boot, repeated captures should be identical. Any region that *changes* between two
captures taken at different points in the loop is carrying live state.

Read-only. Single MEMORY_DEBUG session per capture; no uploads, no mode switches.

Usage
    python live_probe.py                # one capture
    python live_probe.py --twice        # two captures with a delay, diffed
    python live_probe.py --delay 45
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import handshake_memory_debug, mem_read, open_device  # noqa: E402

OUT = Path(__file__).resolve().parent / "live_probe"
T0 = time.time()

#: Small regions always worth reading, with what they mean.
DIAG = [
    (0x81B75038, 4, "RST_STAT"),
    (0x81B75048, 8, "PMIC_PON"),
    (0x81B75058, 264, "PMON_HIS"),
    (0x81B75008, 4, "FSM_STS"),
    (0x81B75018, 4, "FSM_CTRL"),
    (0x81B75028, 4, "DBG_EN"),
]

#: Regions to hash for the change-detection test.
HASH_REGIONS = [
    (0x24020000, 0x2000, "SHRM_HEAD"),
    (0x81B75000, 0x1000, "PMIC_BLOCK"),
    (0x14680000, 0x2000, "OCIMEM_HEAD"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def decode_plog(blob: bytes) -> None:
    """PMON_HIS is a PLOG: 'PLOG' + u32, then records of u8 len + len bytes."""
    idx = blob.find(b"PLOG")
    if idx < 0:
        log("    no PLOG magic in PMON_HIS")
        return
    off = idx + 8
    n = 0
    while off < len(blob) and n < 60:
        ln = blob[off]
        if ln == 0 or off + 1 + ln > len(blob):
            break
        rec = blob[off + 1:off + 1 + ln]
        log(f"      rec[{n:>2}] len={ln:>2}  {rec.hex(' ')}")
        off += 1 + ln
        n += 1


def capture(delay_budget: float = 120.0) -> dict | None:
    """Take one capture. Returns None if the node is not usable."""
    end = time.time() + delay_budget
    link = tables = None
    while time.time() < end:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception as err:  # noqa: BLE001
            log(f"  handshake: {type(err).__name__}")
            link = tables = None
        if tables:
            break
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        # wait for the next enumeration before retrying
        end2 = time.time() + 70
        while time.time() < end2 and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.05)
    if not tables:
        return None

    result = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "regions": len(tables),
        "diag": {},
        "hashes": {},
    }

    for addr, n, name in DIAG:
        blob = mem_read(link, addr, n, tmo=4.0)
        if n == 8:
            val = struct.unpack_from("<Q", blob, 0)[0] if len(blob) >= 8 else None
        elif n == 4:
            val = struct.unpack_from("<I", blob, 0)[0] if len(blob) >= 4 else None
        else:
            val = None
        result["diag"][name] = val
        log(f"  {name:<10} = {val if val is None else hex(val)}")
        if name == "PMON_HIS" and blob:
            decode_plog(blob)
            (OUT / f"pmon_his_{result['when'].replace(':', '')}.bin").write_bytes(blob)

    for addr, ln, name in HASH_REGIONS:
        blob = mem_read(link, addr, ln, tmo=6.0)
        if blob:
            result["hashes"][name] = hashlib.sha256(blob).hexdigest()[:16]
            log(f"  {name:<14} sha256={result['hashes'][name]}")

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--twice", action="store_true", help="capture twice and diff")
    ap.add_argument("--delay", type=float, default=45.0)
    ap.add_argument("--budget", type=float, default=120.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    print("=" * 74)
    print("#  live probe")
    print("=" * 74)

    log("capture 1")
    a = capture(args.budget)
    if a is None:
        log("no usable session - the node may be a zombie; power cycle needed")
        return 1

    if not args.twice:
        path = OUT / "capture.json"
        path.write_text(json.dumps(a, indent=2))
        log(f"  written to {path}")
        return 0

    log(f"waiting {args.delay:.0f}s (device should cycle through boot)")
    time.sleep(args.delay)

    log("capture 2")
    b = capture(args.budget)
    if b is None:
        log("second capture failed")
        return 1

    print()
    print("=" * 74)
    print("#  DIFF between captures")
    print("=" * 74)
    changed = []
    for k in a["diag"]:
        va, vb = a["diag"].get(k), b["diag"].get(k)
        same = va == vb
        log(f"  {k:<10} {va} -> {vb}   {'same' if same else 'CHANGED'}")
        if not same:
            changed.append(k)

    log("")
    for k in a["hashes"]:
        ha, hb = a["hashes"].get(k), b["hashes"].get(k)
        same = ha == hb
        log(f"  {k:<14} {ha} -> {hb}   {'same' if same else 'CHANGED'}")
        if not same:
            changed.append(k)

    print()
    if changed:
        print(f"  Regions that changed: {', '.join(changed)}")
        print("  Live state was found. Those regions carry values that differ between")
        print("  two points in the boot loop, so they are worth decoding next.")
    else:
        print("  Nothing changed. Either both captures landed at the same point in")
        print("  the loop, or the device is not cycling state between boots.")
        print("  Note: identical captures are also what a fully deterministic failure")
        print("  looks like - which is consistent with the silent-failure hypothesis.")

    out = OUT / "captures.json"
    out.write_text(json.dumps({"a": a, "b": b}, indent=2))
    log(f"  written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
