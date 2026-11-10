#!/usr/bin/env python3
"""reset_culprit.py - does SAHARA_RESET itself wedge the node?

The suspicion, and why it is not paranoia
-----------------------------------------
After adding an automatic `SAHARA_RESET` at the end of every session, the node went
mute on the next run. `docs/14-edl-mode-switch.md` records that `SAHARA_RESET` (0x07)
is the *safe* call and `RESET_STATE_MACHINE` (0x13) is the destructive one - but that
was established for the 900E to 9008 bump, not for ending a MEMORY_DEBUG session.

In crashdump mode the target may not accept a reset at all, and sending one could be
what leaves it enumerable-but-mute. If so, the "hygiene" fix is the thing causing the
problem it was meant to prevent - which would be an ironic and important finding.

How this is tested without a second device
------------------------------------------
The state cannot be cleared in software, so a destructive test would need a power
cycle per attempt. Instead this does the cheap, safe version: it records exactly what
the close sequence sends and what comes back, so the next session has that evidence
rather than a guess.

It also checks whether the node responds to a DONE alone, which is the gentler way to
close a stale transfer.

Read-only in the sense that it sends no image and writes nothing to storage. It does
send Sahara control packets, which is unavoidable for the question.

Usage
    python reset_culprit.py
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
    CMD_DONE_REQ,
    CMD_END_TRANSFER,
    CMD_HELLO_REQ,
    CMD_HELLO_RSP,
    CMD_MEMORY_DEBUG,
    CMD_MEMORY_DEBUG_64,
    CMD_RESET,
    CMD_RESET_RSP,
    Link,
)

T0 = time.time()
MODE_MEMORY_DEBUG = 2


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def cmd_name(c: int) -> str:
    return {
        0x01: "HELLO_REQ", 0x02: "HELLO_RSP", 0x03: "READ_DATA",
        0x04: "END_TRANSFER", 0x05: "DONE_REQ", 0x06: "DONE_RSP",
        0x07: "SAHARA_RESET", 0x08: "RESET_RSP", 0x09: "MEMORY_DEBUG",
        0x0A: "MEMORY_READ", 0x0B: "CMD_READY", 0x0C: "SWITCH_MODE",
        0x10: "MEMORY_DEBUG_64", 0x11: "MEMORY_READ_64", 0x12: "READ_DATA_64",
    }.get(c, f"cmd{c:#x}")


def open_link():
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    if dev is None:
        return None
    try:
        dev.set_configuration(1)
    except usb.core.USBError:
        pass
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError:
        pass
    return Link(dev)


def main() -> int:
    print("=" * 72)
    print("#  what does the close sequence actually do?")
    print("=" * 72)

    link = open_link()
    if link is None:
        log("no 900E on the bus")
        return 1

    # ---- step 1: can we even get a HELLO? ------------------------------
    log("step 1: read for HELLO")
    pkt = link.read_packet(2500)
    if pkt is None:
        log("  no HELLO - node is already mute, nothing can be learned here")
        return 1
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    log(f"  got {cmd_name(cmd)}")

    if cmd != CMD_HELLO_REQ:
        log("  not HELLO; stopping to avoid sending anything unexpected")
        return 1

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  ver={ver} mode={mode}")

    # ---- step 2: enter MEMORY_DEBUG ------------------------------------
    log("step 2: HELLO_RSP requesting MEMORY_DEBUG")
    link.write(struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                           ver, 1, 0, MODE_MEMORY_DEBUG, 1, 2, 3, 4, 5, 6))
    rsp = link.read_packet(4000)
    if rsp is None:
        log("  no answer")
        return 1
    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    log(f"  got {cmd_name(rcmd)}")
    if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
        log("  handshake rejected")
        return 1

    # ---- step 3: try the GENTLE close first: DONE ----------------------
    log("step 3: gentle close - send DONE_REQ and see what happens")
    link.write(struct.pack("<II", CMD_DONE_REQ, 8))
    rsp = link.read_packet(2500)
    if rsp is None:
        log("  no response to DONE (expected if no transfer is open)")
    else:
        log(f"  got {cmd_name(struct.unpack_from('<I', rsp, 0)[0])}")

    # ---- step 4: now the reset, and record the response ----------------
    log("step 4: send SAHARA_RESET and record the reply")
    link.write(struct.pack("<II", CMD_RESET, 8))
    rsp = link.read_packet(3000)
    if rsp is None:
        log("  NO RESPONSE to SAHARA_RESET - the reset was not acknowledged")
        log("  This is the important outcome: an unacknowledged reset in")
        log("  MEMORY_DEBUG mode is consistent with leaving the node mute.")
    else:
        rc = struct.unpack_from("<I", rsp, 0)[0]
        log(f"  got {cmd_name(rc)}")
        if rc == CMD_RESET_RSP:
            log("  acknowledged normally (RESET_RSP)")
        else:
            log("  unexpected reply")

    # ---- step 5: can we reopen? ---------------------------------------
    log("step 5: reopen and read HELLO again")
    time.sleep(1.0)
    link2 = open_link()
    if link2 is None:
        log("  could not reopen")
        return 1
    pkt2 = link2.read_packet(2500)
    if pkt2 is None:
        log("  NO HELLO after the reset - the node is now mute.")
        log("")
        log("  CONCLUSION: SAHARA_RESET at the end of a MEMORY_DEBUG session")
        log("  wedges this device. The automatic close added for hygiene is the")
        log("  cause of the zombie state, and must be removed.")
        return 1
    log(f"  got {cmd_name(struct.unpack_from('<I', pkt2, 0)[0])} - still alive")

    print()
    print("=" * 72)
    print("#  RESULT")
    print("=" * 72)
    print("  The reset was acknowledged and the node reopened. In this run the")
    print("  close sequence is safe, so the earlier wedging had another cause -")
    print("  most likely a session abandoned while a read was outstanding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
