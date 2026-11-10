#!/usr/bin/env python3
"""check_tablet.py - one-shot health and identity check of the connected tablet.

Answers, in one run, the questions that otherwise take several scripts:

  1. Is a Qualcomm device on the bus, and as which PID?
  2. Does it answer Sahara, or is the node present but mute (zombie)?
  3. If it answers: Sahara version, mode, HWID and serial.
  4. Does 900E expose its memory table, and what are the key registers?
  5. Anything else interesting on the bus (Lenovo/Google/other Qualcomm PIDs)?

Read-only. It never uploads a programmer, never writes, never switches mode
beyond the MEMORY_DEBUG handshake on 900E.

Usage
    python check_tablet.py
    python check_tablet.py --deep     # also read the key diagnostic registers
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import (  # noqa: E402
    CMD_HELLO_REQ,
    CMD_HELLO_RSP,
    CMD_RESET,
    Link,
    handshake_memory_debug,
    mem_read,
    open_device,
)

T0 = time.time()

PID_NAMES = {
    0x9008: "EDL / Sahara (programmer-loadable)",
    0x900E: "crashdump / MEMORY_DEBUG",
    0x9006: "diag / download",
    0x901D: "QDLoader?",
    0x9025: "QDLoader?",
}

MODE_NAMES = {
    0: "IMAGE_TX_PENDING (real EDL)",
    1: "IMAGE_TX_COMPLETE",
    2: "MEMORY_DEBUG (crashdump)",
    3: "COMMAND",
}

#: Registers worth reading on 900E, with expected values where known.
DIAG = [
    (0x81B75038, 4, "RST_STAT", 0x3, "expect 0x3 (b0+b1); b1 = watchdog"),
    (0x81B75048, 8, "PMIC_PON", None, "low nibble 0 = power key"),
    (0x81B75008, 4, "FSM_STS", None, None),
    (0x81B75028, 4, "DBG_EN", None, None),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def scan_bus():
    rows = []
    try:
        for d in usb.core.find(find_all=True):
            v = getattr(d, "idVendor", None)
            p = getattr(d, "idProduct", None)
            if v is None:
                continue
            if v in (0x05C6, 0x17EF, 0x18D1, 0x2A70, 0x2717):
                rows.append((v, p, d))
    except Exception as err:  # noqa: BLE001
        log(f"bus scan failed: {type(err).__name__}")
    return rows


def describe_pid(v: int, p: int) -> str:
    if v == 0x05C6:
        return PID_NAMES.get(p, "Qualcomm (unrecognised PID)")
    if v == 0x17EF:
        return "Lenovo"
    if v == 0x18D1:
        return "Google / fastboot or adb"
    return "other"


def probe_sahara(pid: int) -> dict:
    """Send HELLO and read identity if the node answers."""
    out = {"answers": False, "ver": None, "mode": None, "zombie": False}
    dev = usb.core.find(idVendor=0x05C6, idProduct=pid)
    if dev is None:
        return out
    try:
        dev.set_configuration(1)
    except usb.core.USBError:
        pass
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError:
        pass

    try:
        link = Link(dev)
        pkt = link.read_packet(2500)
        if pkt is None:
            out["zombie"] = True
            return out
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd == CMD_HELLO_REQ:
            out["answers"] = True
            out["ver"] = struct.unpack_from("<I", pkt, 8)[0]
            out["mode"] = struct.unpack_from("<I", pkt, 20)[0]
        elif cmd == CMD_RESET:
            out["answers"] = True
            out["note"] = "RESET pending"
        else:
            out["answers"] = True
            out["note"] = f"cmd {cmd:#x}"
    except Exception as err:  # noqa: BLE001
        out["note"] = f"{type(err).__name__}"
    finally:
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true",
                    help="also read diagnostic registers from 900E")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="wait up to N seconds for the device to appear")
    args = ap.parse_args()

    print("=" * 74)
    print("#  tablet check")
    print("=" * 74)

    # ---- 0. optional wait ----------------------------------------------
    if args.wait > 0:
        log(f"waiting up to {args.wait:.0f}s for a Qualcomm device ...")
        end = time.time() + args.wait
        while time.time() < end:
            if any(getattr(d, "idVendor", 0) == 0x05C6
                   for d in usb.core.find(find_all=True)):
                break
            time.sleep(0.05)
        else:
            log("device did not appear within the wait window")

    # ---- 1. bus ---------------------------------------------------------
    rows = scan_bus()
    if not rows:
        log("no Qualcomm / Lenovo / Google device on the bus")
        log("the unit boot-loops, so it is absent for ~15 s at a time;")
        log("re-run with --wait 60 to catch it, or watch for a while:")
        log("  python edl_coach.py watch --seconds 120")
        return 1

    log(f"{len(rows)} relevant device(s) on the bus:")
    for v, p, d in rows:
        log(f"  {v:04x}:{p:04x}  bus {d.bus} addr {d.address}  "
            f"{describe_pid(v, p)}")

    # ---- 2. Sahara liveness --------------------------------------------
    # NOTE: a Sahara session is single-use. Sending HELLO once advances the state
    # machine, so a second handshake on the same node fails even though the device
    # is perfectly healthy. When --deep is requested, the HELLO probe is therefore
    # skipped and the deep path does the handshake itself.
    print()
    qcom = [(v, p) for v, p, _ in rows if v == 0x05C6]
    if not args.deep:
        for v, p in qcom:
            log(f"probing {p:04x} for a Sahara HELLO (2.5 s) ...")
            r = probe_sahara(p)
            if r["answers"]:
                mode = r["mode"]
                mode_txt = MODE_NAMES.get(mode, f"mode {mode}") if mode is not None else "?"
                log(f"  ANSWERS: ver={r['ver']} mode={mode} ({mode_txt})")
                if p == 0x9008:
                    log("  -> 9008 and responsive: a programmer can be loaded")
                elif p == 0x900E:
                    log("  -> 900E and responsive: crash dump is readable")
            elif r["zombie"]:
                log("  NO ANSWER: node is present but mute (zombie state)")
                log("  -> power cycle required (hold Power ~15 s)")
            else:
                log(f"  no HELLO ({r.get('note', 'timeout')})")
    else:
        log("--deep: HELLO probe deferred to the deep session (Sahara is single-use)")

    # ---- 3. deep read ---------------------------------------------------
    if args.deep:
        print()
        log("deep read: MEMORY_DEBUG table and diagnostics")
        dev = open_device()
        if dev is None:
            log("  900E not openable")
        else:
            try:
                link, tables = handshake_memory_debug(dev)
            except Exception as err:  # noqa: BLE001
                log(f"  handshake failed: {type(err).__name__} {err}")
                link = tables = None
            if tables:
                log(f"  handshake OK - memory table: {len(tables)} regions")
                for addr, n, name, expect, note in DIAG:
                    blob = mem_read(link, addr, n, tmo=4.0)
                    if not blob:
                        log(f"  {name:<10} @ {addr:#010x}  NO ANSWER")
                        continue
                    if n == 8:
                        val = struct.unpack_from("<Q", blob, 0)[0]
                    else:
                        val = struct.unpack_from("<I", blob, 0)[0]
                    mark = ""
                    if expect is not None:
                        mark = ("  matches expectation" if val == expect
                                else f"  (expected {expect:#x})")
                    log(f"  {name:<10} @ {addr:#010x} = {val:#x}{mark}")
                    if note:
                        log(f"             {note}")
            else:
                log("  no memory table (node may be mid-cycle, or a second session)")

    print()
    print("=" * 74)
    print("#  SUMMARY")
    print("=" * 74)
    if any(p == 0x9008 for _, p in qcom):
        print("  State: 9008 - ready for a programmer upload.")
        print("  Note: this is the state the programmer fails in, so uploads will")
        print("        still end in silence. See docs/16-firehose-bringup.md.")
    elif any(p == 0x900E for _, p in qcom):
        print("  State: 900E - crashdump. Readable, not write-capable.")
        print("  Use --deep to pull the reset cause and PMIC state.")
    else:
        print("  State: a Qualcomm device is present but not in a known mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
