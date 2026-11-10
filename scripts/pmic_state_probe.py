#!/usr/bin/env python3
"""pmic_state_probe.py - read the crash-dump regions that failed before.

Why this specific target
------------------------
docs/05-firehose-and-the-silence.md leaves exactly two explanations for the
programmer's silence, and states that the host cannot tell them apart:

  6.1  the programmer dies during DDR bring-up
  6.2  the programmer is shut down by its own battery guard (DBC)

Hypothesis 6.2 has a piece of evidence nobody has read yet: the device's crash
dump exposes `sbl_pmic_dump.bin` - 512 KiB at 0x1000000000, SBL's own PMIC state
- and `SHRM_MEM.BIN` at 0x24020000, the shared-memory area. Earlier attempts
timed out on both (bootstage_probe got 0 bytes from each) and the result was
never revisited.

Those two regions are where VBAT, charger presence, charger type and PMIC fault
state would live. If SBL recorded a low/absent battery or "charger not charging"
at hand-off, hypothesis 6.2 becomes a measurement rather than a guess - and the
remedy changes (external bench supply vs. giving up on host-side work).

Method
------
Chunked reads (same 512 KiB granularity edlclient's read_memory uses), generous
per-chunk timeouts, and a retry across power cycles, because a zombie 9008 or a
stale 900E makes every read return empty for reasons unrelated to the data.

Read-only. No mode switch beyond the MEMORY_DEBUG handshake, no upload.

Usage
    python pmic_state_probe.py
    python pmic_state_probe.py --time 300
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

from crash_region_probe import Link, handshake_memory_debug, open_device  # noqa: E402

OUT = Path(__file__).resolve().parent / "pmic_state_probe"
T0 = time.time()

CMD_MEMORY_READ_64 = 0x11
CHUNK = 0x080000  # 512 KiB, what edlclient uses

#: Regions worth retrying, plus the small diagnostics for context.
TARGETS = [
    "sbl_pmic_dump.bin",
    "SHRM_MEM.BIN",
    "OCIMEM.BIN",
    "CODERAM.BIN",
    "DATARAM.BIN",
    "SMEMINFO.BIN",
    "SMEM_VER.BIN",
    "PMIC_PON.BIN",
    "RST_STAT.BIN",
]

#: Strings that would confirm or refute the DBC / charger theory.
MARKERS = [
    b"VBAT", b"vbatt", b"charger", b"Charger", b"CHG", b"chg",
    b"battery", b"Battery", b"BATT", b"usb", b"USB", b"SDP", b"CDP", b"DCP",
    b"shutdown", b"Shutdown", b"low", b"LOW", b"threshold", b"DBC",
    b"PMIC", b"pmic", b"pon", b"PON", b"fault", b"FAULT", b"OCV", b"SoC",
    b"SBL", b"XBL", b"boot", b"Boot", b"wdog", b"WDog", b"WDOG",
]


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def read_chunked(link: Link, addr: int, length: int, tmo: float = 20.0) -> bytes:
    """Read in CHUNK pieces so a single long transfer cannot time out silently."""
    got = bytearray()
    pos = 0
    while pos < length:
        n = min(CHUNK, length - pos)
        pkt = struct.pack("<IIQQ", CMD_MEMORY_READ_64, 8 + 8 + 8, addr + pos, n)
        try:
            link.write(pkt)
        except Exception as err:  # noqa: BLE001
            log(f"      write failed at +{pos:#x}: {type(err).__name__}")
            break
        deadline = time.time() + tmo
        chunk = bytearray()
        while len(chunk) < n and time.time() < deadline:
            try:
                b = link._fill(200)
            except Exception:  # noqa: BLE001
                break
            if not b:
                continue
            chunk += b
        if not chunk:
            break
        got += chunk[:n]
        pos += len(chunk[:n])
        if len(chunk) < n:
            break
    return bytes(got)


def strings(blob: bytes, minlen: int = 4) -> list[str]:
    return [m.group().decode("ascii", "replace")
            for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, blob)]


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
            log(f"  handshake: {type(err).__name__} {err}")
            link = tables = None
        if tables:
            return link, tables
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        log("  no table - waiting for the device to cycle")
        end = time.time() + 70
        while time.time() < end and (
                usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None
                or usb.core.find(idVendor=0x05C6, idProduct=0x9008) is not None):
            time.sleep(0.05)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=240.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 74)
    log("#  pmic_state_probe - does SBL's own dump explain the shutdown?")
    log("=" * 74)

    link, tables = wait_session(args.time)
    if not tables:
        log(">>> no usable crashdump session. The tablet is probably in the")
        log(">>> zombie 9008 state; it needs a power cycle (hold Power ~15 s).")
        return 1

    names = {e["file"]: e for e in tables}
    log(f"  table has {len(tables)} entries")

    saved = {}
    for want in TARGETS:
        e = names.get(want)
        if not e:
            log(f"  {want:<20s} not offered by the device")
            continue
        log("")
        log(f"  {want}  {e['len']} B @ {e['addr']:#x}")
        blob = read_chunked(link, e["addr"], e["len"])
        log(f"    read {len(blob)}/{e['len']} B")
        if not blob:
            continue
        (OUT / want).write_bytes(blob)
        saved[want] = blob

        nz = sum(1 for b in blob if b)
        log(f"    nonzero {nz}/{len(blob)} ({nz/max(1,len(blob)):.1%})")

        strs = strings(blob)
        hits, seen = [], set()
        for s in strs:
            if any(m.decode() in s for m in MARKERS) and s not in seen:
                seen.add(s)
                hits.append(s)
        if hits:
            log(f"    {len(hits)} relevant strings:")
            for s in hits[:45]:
                log(f"      | {s[:110]}")
            if len(hits) > 45:
                log(f"      ... {len(hits) - 45} more")

    # ---- interpretation ---------------------------------------------------
    log("")
    log("=" * 74)
    log("#  RESULT")
    log("=" * 74)
    if "sbl_pmic_dump.bin" in saved:
        blob = saved["sbl_pmic_dump.bin"]
        log(f"  sbl_pmic_dump.bin read: {len(blob)} B - THIS IS NEW")
        log("  Search it for VBAT / charger words above. A recorded low or absent")
        log("  battery at hand-off supports hypothesis 6.2 (DBC shutdown); a clean")
        log("  battery state pushes the failure back to DDR bring-up (6.1).")
    else:
        log("  sbl_pmic_dump.bin still not read.")
    log("")
    log(f"  artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
