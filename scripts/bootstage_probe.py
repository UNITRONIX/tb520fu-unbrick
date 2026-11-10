#!/usr/bin/env python3
"""bootstage_probe.py - how far does boot actually get?

Reads the crash-dump regions that can carry boot-stage evidence, then searches
them for strings instead of dumping hex. Read-only.

Regions grabbed (from the device's own memory table, addresses never guessed):
    sbl_pmic_dump.bin  512 KiB  SBL's own dump - PMIC/PON + early boot state
    CD_BTDDR.BIN       256 KiB  crash-dump context at DDR base
    CD_STRCT.BIN       488 B    crash-dump structure
    SMEMINFO.BIN       768 B    shared-memory boot info
    SMEMSHRM            via SHRM_MEM.BIN, 256 KiB

The question this answers: did XBL finish (logo means yes), did ABL start, and
what reset us (RST_STAT already says watchdog).

Usage
    python bootstage_probe.py
    python bootstage_probe.py --time 180
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import Link, handshake_memory_debug, mem_read, open_device  # noqa: E402

OUT = Path(__file__).resolve().parent / "bootstage_probe"
T0 = time.time()

#: Substrings that indicate a boot stage or a failure reason.
MARKERS = [
    b"ABL", b"abl", b"LinuxLoader", b"ROCKNIX", b"UEFI", b"XBL", b"SBL", b"PBL",
    b"watchdog", b"WDOG", b"WDT", b"DDR", b"training", b"Training",
    b"charger", b"battery", b"VBAT", b"shutdown", b"Shutdown",
    b"panic", b"PANIC", b"fault", b"Fault", b"abort", b"reset", b"Reset",
    b"boot", b"Boot", b"fastboot", b"slot", b"slot_", b"BCB", b"misc",
    b"lapis", b"TB520FU", b"pineapple", b"LANAI",
]


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def strings(blob: bytes, minlen: int = 5) -> list[str]:
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, blob):
        out.append(m.group().decode("ascii", "replace"))
    return out


def wait_session(budget: float):
    deadline = time.time() + budget
    while time.time() < deadline:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception as err:  # noqa: BLE001
            log(f"  handshake exception {type(err).__name__}: {err}")
            link = tables = None
        if tables:
            return link, tables
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        end = time.time() + 60
        while time.time() < end and usb.core.find(idVendor=0x05C6, idProduct=0x900E):
            time.sleep(0.05)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=150.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 72)
    log("#  bootstage_probe - what does the crash dump remember about boot?")
    log("=" * 72)

    link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable 900E session")
        return 1

    names = {e["file"]: e for e in tables}
    targets = ["CD_STRCT.BIN", "SMEMINFO.BIN", "CD_BTDDR.BIN",
               "sbl_pmic_dump.bin", "SHRM_MEM.BIN"]

    for want in targets:
        e = names.get(want)
        if not e:
            log(f"  {want:<20s} not in table")
            continue
        log("")
        log(f"  reading {want} ({e['len']} B @ {e['addr']:#x})")
        blob = mem_read(link, e["addr"], e["len"], tmo=15.0)
        log(f"    got {len(blob)} B")
        if not blob:
            continue
        fn = OUT / want
        fn.write_bytes(blob)

        strs = strings(blob)
        log(f"    {len(strs)} printable strings")
        hits = [s for s in strs if any(m.decode() in s for m in MARKERS)]
        # dedupe, keep order, cap output
        seen, uniq = set(), []
        for s in hits:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        for s in uniq[:40]:
            log(f"      | {s[:100]}")
        if len(uniq) > 40:
            log(f"      ... {len(uniq) - 40} more")

    # CD_STRCT is a structure, so show its fields directly
    cs = OUT / "CD_STRCT.BIN"
    if cs.exists():
        blob = cs.read_bytes()
        log("")
        log("#  CD_STRCT.BIN as u32 words (first 32)")
        for i in range(0, min(len(blob), 128), 16):
            words = struct.unpack_from("<4I", blob, i)
            log(f"    {i:>4}  " + "  ".join(f"{w:#010x}" for w in words))

    log("")
    log("=" * 72)
    log(f"artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
