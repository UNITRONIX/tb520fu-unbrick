#!/usr/bin/env python3
"""single_session.py - do the whole experiment inside one Sahara session.

The constraint that forces this design
--------------------------------------
HELLO is a single pending packet. Measured repeatedly this session:

    check_tablet.py   gets HELLO
    baseline_capture  no HELLO, 5 s later, same node
    direct probe      timeout

and the device does not generate a new one because it is not rebooting - it waits at
900E indefinitely until something sends it a command (docs/23-no-boot-loop.md).

So the budget is: **one HELLO per power cycle.** Anything that opens the device
consumes it. That makes the obvious approach - probe first, then capture - impossible.

The workable sequence
---------------------
Everything that needs the crash dump must happen in a single session, in this order:

    1. open 900E, read HELLO                      (the one and only)
    2. HELLO_RSP(MEMORY_DEBUG)                    -> memory table
    3. capture all regions                        (this is the baseline)
    4. read the diagnostic registers              (same session, still valid)
    5. close

Then, separately:

    6. bump to 9008, upload, let the programmer reset the device
    7. the device returns to 900E with a FRESH HELLO
    8. capture again - a new session, a new HELLO

So the experiment spans exactly two HELLOs: one before the upload, one after. That is
enough, because the comparison is before-vs-after, not sample-vs-sample.

Read-only. One session per phase.

Usage
    python single_session.py capture --label before
    python single_session.py upload --melf <path>     # then capture --label after
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import (  # noqa: E402
    CMD_CMD_READY,
    CMD_DONE_REQ,
    CMD_END_TRANSFER,
    CMD_HELLO_REQ,
    CMD_HELLO_RSP,
    CMD_MEMORY_DEBUG,
    CMD_MEMORY_DEBUG_64,
    CMD_READ_DATA,
    CMD_RESET,
    CMD_RESET_RSP,
    Link,
    mem_read,
)

OUT = Path(__file__).resolve().parent / "single_session"
T0 = time.time()

MODE_COMMAND = 3
MODE_IMAGE_TX = 0
MODE_MEMORY_DEBUG = 2
MIN_SENT = 1_500_000

REGIONS = [
    (0x14680000, 0x1000, "OCIMEM"),
    (0x81B75000, 0x1000, "PMIC"),
    (0x24020000, 0x1000, "SHRM"),
]
DIAG = [
    (0x81B75038, 4, "RST_STAT"),
    (0x81B75048, 8, "PMIC_PON"),
    (0x81B75008, 4, "FSM_STS"),
]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def pid():
    for p in (0x900E, 0x9008):
        if usb.core.find(idVendor=0x05C6, idProduct=p) is not None:
            return p
    return None


def open_dev(which: int):
    dev = usb.core.find(idVendor=0x05C6, idProduct=which)
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
    return dev


def close_dev(dev) -> None:
    if dev is None:
        return
    try:
        usb.util.release_interface(dev, 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        usb.util.dispose_resources(dev)
    except Exception:  # noqa: BLE001
        pass


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


# ---------------------------------------------------------------------------
def cmd_capture(label: str) -> int:
    """One complete crash-dump session: HELLO -> table -> regions -> diag."""
    log(f"capture '{label}' - one session, one HELLO")
    if pid() != 0x900E:
        log(f"  device is at {pid():04x}" if pid() else "  no device")
        log("  capture needs 900E; a power cycle or the programmer's own reset gets you there")
        return 1

    dev = open_dev(0x900E)
    if dev is None:
        log("  900E not openable")
        return 1

    try:
        link = Link(dev)
        pkt = link.read_packet(2500)
        if pkt is None:
            log("  NO HELLO.")
            log("  Almost always this means the HELLO was already consumed by another")
            log("  open since the last reset. Power cycle, then run this FIRST.")
            return 1

        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO, got {cmd:#x}")
            return 1

        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  HELLO ver={ver} mode={mode}")

        link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = link.read_packet(4000)
        if rsp is None:
            log("  no MEMORY_DEBUG reply")
            return 1
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd == CMD_MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
        elif rcmd == CMD_MEMORY_DEBUG_64:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
        else:
            log(f"  unexpected reply {rcmd:#x}")
            return 1
        log(f"  memory table @ {tbl_addr:#x} len {tbl_len}")

        result = {"label": label, "regions": {}, "diag": {}, "hashes": {}}
        OUT.mkdir(exist_ok=True)

        for addr, ln, name in REGIONS:
            blob = mem_read(link, addr, ln, tmo=8.0)
            if not blob:
                log(f"  {name}: no data")
                continue
            result["regions"][name] = blob
            h = hashlib.sha256(blob).hexdigest()[:16]
            result["hashes"][name] = h
            log(f"  {name:<8} {len(blob)} B  sha256={h}")
            (OUT / f"{label}_{name}.bin").write_bytes(blob)

        for addr, n, name in DIAG:
            blob = mem_read(link, addr, n, tmo=4.0)
            if not blob:
                continue
            val = (struct.unpack_from("<Q", blob, 0)[0] if n == 8
                   else struct.unpack_from("<I", blob, 0)[0])
            result["diag"][name] = val
            log(f"  {name:<8} = {val:#x}")

        (OUT / f"{label}.json").write_text(json.dumps(
            {"hashes": result["hashes"], "diag": result["diag"]}, indent=2))
        log(f"  saved {label}.json")
        return 0
    finally:
        close_dev(dev)


# ---------------------------------------------------------------------------
def cmd_upload(melf: str) -> int:
    path = Path(melf)
    if not path.is_file():
        log(f"not found: {path}")
        return 2
    payload = path.read_bytes()
    log(f"payload {path.name}  {len(payload)} B")

    if pid() != 0x900E:
        log(f"  device is at {pid():04x}" if pid() else "  no device")
        return 1

    # ---- bump: consumes this HELLO, that is fine ----------------------
    log("bump 900E -> 9008")
    dev = open_dev(0x900E)
    if dev is None:
        return 1
    try:
        link = Link(dev)
        pkt = link.read_packet(2500)
        if pkt is None:
            log("  no HELLO to bump with (already consumed?)")
            return 1
        if struct.unpack_from("<I", pkt, 0)[0] != CMD_HELLO_REQ:
            log("  not HELLO")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        link.write(hello_rsp(ver, MODE_COMMAND))
        r = link.read_packet(3000)
        if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
            log("  command mode refused")
            return 1
        link.write(struct.pack("<III", 0x0C, 12, MODE_IMAGE_TX))
        r = link.read_packet(4000)
        if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
            log("  switch not confirmed")
            return 1
        link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
        r = link.read_packet(4000)
        if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
            link.write(struct.pack("<II", CMD_DONE_REQ, 8))
            link.read_packet(2000)
        log("  switched")
    finally:
        close_dev(dev)

    end = time.time() + 50
    while time.time() < end and pid() != 0x9008:
        time.sleep(0.1)
    if pid() != 0x9008:
        log("  9008 did not appear")
        return 1
    log("  at 9008")

    # ---- upload -------------------------------------------------------
    dev = open_dev(0x9008)
    if dev is None:
        return 1
    try:
        link = Link(dev)
        pkt = link.read_packet(5000)
        if pkt is None:
            log("  no HELLO on 9008")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        log(f"  9008 HELLO ver={ver}")
        link.write(hello_rsp(ver, MODE_IMAGE_TX))

        sent = 0
        status = None
        while True:
            pkt = link.read_packet(8000)
            if pkt is None:
                status = f"timeout after {sent}"
                break
            c = struct.unpack_from("<I", pkt, 0)[0]
            if c == CMD_READ_DATA:
                _i, off, dlen = struct.unpack_from("<III", pkt, 8)
            elif c == 0x12:
                _i, off, dlen = struct.unpack_from("<IQQ", pkt, 8)
            elif c == CMD_END_TRANSFER:
                status = struct.unpack_from("<I", pkt, 12)[0] if len(pkt) >= 16 else -1
                break
            else:
                status = f"cmd {c:#x}"
                break
            chunk = payload[off:off + dlen]
            if len(chunk) < dlen:
                chunk += b"\xff" * (dlen - len(chunk))
            link.write(chunk)
            sent += len(chunk)

        log(f"  END={status} sent={sent}")
        if status == 0 and sent >= MIN_SENT:
            link.write(struct.pack("<II", CMD_DONE_REQ, 8))
            link.read_packet(3000)
            log("  DONE acknowledged")
    finally:
        close_dev(dev)

    log("waiting for the programmer to reset the device back to 900E")
    end = time.time() + 60
    while time.time() < end:
        if pid() == 0x900E:
            log("  back at 900E - a fresh HELLO is now pending")
            return 0
        time.sleep(0.2)
    log(f"  still at {pid():04x}" if pid() else "  device absent")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("capture")
    p1.add_argument("--label", required=True)

    p2 = sub.add_parser("upload")
    p2.add_argument("--melf", required=True)

    args = ap.parse_args()

    if args.cmd == "capture":
        return cmd_capture(args.label)
    if args.cmd == "upload":
        return cmd_upload(args.melf)
    return 2


if __name__ == "__main__":
    sys.exit(main())
