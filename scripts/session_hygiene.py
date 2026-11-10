#!/usr/bin/env python3
"""session_hygiene.py - verify that MEMORY_DEBUG sessions close cleanly.

The problem this exists to prevent
----------------------------------
Fourteen scripts in this repository open a Sahara MEMORY_DEBUG session. If a session
is abandoned mid-handshake the target is left in a state that is *enumerable but
mute*: it appears in PnP, every subsequent open fails or hangs, and only a power
cycle clears it. That state has cost several experiment runs, and twice it looked
like a device fault.

Two distinct causes were found:

  1. not sending SAHARA_RESET at the end of a session;
  2. treating "no packet" as "device broken" without retrying past a boot cycle.

This script checks both, mechanically:

  phase 1  confirm the node answers HELLO at all
  phase 2  open MEMORY_DEBUG, read one region, then close with SAHARA_RESET
  phase 3  immediately open a *second* session on the same node

If phase 3 succeeds, the close was clean. If it fails while phase 2 succeeded, the
close path is leaving the node wedged and must be fixed before further experiments.

Read-only.

Usage
    python session_hygiene.py
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import (  # noqa: E402
    CMD_RESET,
    Link,
    close_session,
    handshake_memory_debug,
    mem_read,
    open_device,
)

T0 = time.time()


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def qcom_pid():
    for p in (0x900E, 0x9008):
        if usb.core.find(idVendor=0x05C6, idProduct=p) is not None:
            return p
    return None


def phase_hello() -> bool:
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    if dev is None:
        log("  no 900E on the bus")
        return False
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
    except Exception as err:  # noqa: BLE001
        log(f"  open/read failed: {type(err).__name__}")
        return False
    if pkt is None:
        return False
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    log(f"  HELLO present (cmd={cmd:#x})")
    # leave it clean
    close_session(link)
    return True


def main() -> int:
    print("=" * 70)
    print("#  session hygiene check")
    print("=" * 70)

    pid = qcom_pid()
    log(f"device: {pid:04x}" if pid else "device: none")
    if pid is None:
        log("plug the tablet in")
        return 1

    log("")
    log("phase 1: does the node answer HELLO?")
    if not phase_hello():
        log("  NO - the node is mute.")
        log("")
        log("  This is the zombie state. It cannot be cleared from software:")
        log("    - libusb reset does not re-enumerate it")
        log("    - PnP disable/enable needs administrator rights and usually fails")
        log("  A power cycle (hold Power ~15 s) is the only remedy.")
        return 1
    log("  yes")

    log("")
    log("phase 2: open MEMORY_DEBUG, read one region, close with SAHARA_RESET")
    dev = open_device()
    if dev is None:
        log("  could not open")
        return 1
    link, tables = handshake_memory_debug(dev)
    if not tables:
        log("  handshake failed")
        return 1
    log(f"  table: {len(tables)} regions")
    probe = mem_read(link, 0x81B75038, 4, tmo=4.0)
    log(f"  RST_STAT read: {struct.unpack_from('<I', probe, 0)[0]:#x}"
        if probe else "  RST_STAT read failed")
    close_session(link)
    log("  closed with SAHARA_RESET")

    log("")
    log("phase 3: immediately open a second session")
    time.sleep(0.5)
    dev2 = open_device()
    if dev2 is None:
        log("  FAILED: node not openable after a clean close")
        log("  This means the close path is leaving the node wedged.")
        return 1
    link2, tables2 = handshake_memory_debug(dev2)
    if not tables2:
        log("  FAILED: handshake rejected after a clean close")
        return 1
    log(f"  OK: {len(tables2)} regions on the second session")
    close_session(link2)

    print()
    print("=" * 70)
    print("#  RESULT")
    print("=" * 70)
    print("  Sessions close and reopen cleanly. Experiments can take multiple")
    print("  captures in one run without wedging the device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
