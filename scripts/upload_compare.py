#!/usr/bin/env python3
"""upload_compare.py - where exactly does the programmer die?

The one experiment that isolates the failure
--------------------------------------------
Every session so far uploaded the FULL melf (1 569 028 B) and observed: transfer
OK, END 0x0, DONE, then silence, then the device drops off USB ~8 s later and
comes back as crashdump.

That single observation cannot tell us WHICH stage hung, because the melf is a
container of five images and the last two are the interesting ones:

    image [2]  XBL core        (runs first after the jump)
    image [3]  Firehose        (must raise USB and speak XML)
    image [4]  DDR training    (dcb, pre-DDR DTB, PLL/DRAM)

`xbl_s.melf` is 1 117 008 B - byte-for-byte the prefix of the full melf, i.e.
everything up to but excluding the Firehose image. Uploading it therefore runs
the same XBL + DDR bring-up while never reaching Firehose.

So:

  * if the SHORT upload also goes silent and is watchdog-reset after ~8 s,
    the hang is upstream of Firehose - in XBL or DDR init. Firehose code is
    not even present, so blaming it is impossible.
  * if the SHORT upload behaves differently (different timing, different USB
    behaviour, different END status), then the Firehose stage is implicated and
    the 8 s silence belongs to it.

That is a clean A/B with no writes to storage, and it is the first time it has
been run on this unit.

Also measured here: the precise DONE->disappearance delta, polled at 20 ms, so
the watchdog window can be compared between the two payloads instead of being
estimated from a 1 s poll.

Usage
    python upload_compare.py --payload <ROM>/image/xbl_s.melf --label short
    python upload_compare.py --payload <ROM>/image/xbl_s_devprg_ns.melf --label full
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

from crash_region_probe import Link  # noqa: E402

T0 = time.time()

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_READ_DATA = 0x03
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_DONE_RSP = 0x06
CMD_RESET = 0x07
CMD_CMD_READY = 0x0B
CMD_SWITCH_MODE = 0x0C
CMD_READ_DATA_64 = 0x12

MODE_IMAGE_TX = 0
MODE_COMMAND = 3

#: Below this, an END status of 0 is the zero-byte false success described in
#: docs/03-sahara-protocol.md section 7 and must not be trusted.
MIN_PLAUSIBLE = 4096


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def find(pid: int):
    return usb.core.find(idVendor=0x05C6, idProduct=pid)


def open_pid(pid: int):
    dev = find(pid)
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


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def bump_to_9008(budget: float = 60.0) -> bool:
    """900E -> 9008 using the documented 12-byte switch."""
    end = time.time() + budget
    while time.time() < end:
        dev = open_pid(0x900E)
        if dev is None:
            if find(0x9008) is not None:
                return True
            time.sleep(0.05)
            continue
        try:
            link = Link(dev)
            pkt = link.read_packet(2500)
            if pkt is None:
                link.write(struct.pack("<II", CMD_RESET, 8))
                pkt = link.read_packet(2500)
            if pkt is None:
                raise RuntimeError("no HELLO")
            cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd == CMD_END_TRANSFER:
                link.write(struct.pack("<II", CMD_RESET, 8))
                pkt = link.read_packet(2500)
                if pkt is None:
                    raise RuntimeError("no HELLO after reset")
                cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd != CMD_HELLO_REQ:
                raise RuntimeError(f"expected HELLO, got {cmd:#x}")

            ver = struct.unpack_from("<I", pkt, 8)[0]
            mode = struct.unpack_from("<I", pkt, 20)[0]
            log(f"  bump: HELLO ver={ver} mode={mode}")
            if mode != MODE_IMAGE_TX:
                link.write(hello_rsp(ver, MODE_COMMAND))
                r = link.read_packet(3000)
                if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
                    raise RuntimeError("command mode refused")
                link.write(struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX))
                r = link.read_packet(4000)
                if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
                    raise RuntimeError("switch not confirmed")
                ver = struct.unpack_from("<I", r, 8)[0]
                link.write(hello_rsp(ver, MODE_IMAGE_TX))
                r = link.read_packet(4000)
                if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
                    link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                    link.read_packet(2500)
            log("  bump: switched, waiting for 9008")
        except Exception as err:  # noqa: BLE001
            log(f"  bump attempt failed: {type(err).__name__} {err}")

        t = time.time() + 40
        while time.time() < t:
            if find(0x9008) is not None:
                time.sleep(0.1)
                return True
            time.sleep(0.05)
        # let the node cycle before retrying
        t = time.time() + 40
        while time.time() < t and find(0x900E) is None:
            time.sleep(0.05)
    return False


def upload(payload: bytes, label: str) -> dict:
    """One Sahara upload. Returns timing/status facts, no interpretation."""
    res = {
        "label": label, "size": len(payload), "ok": False,
        "end_status": None, "sent": 0, "reads": 0,
        "done_at": None, "end_at": None, "hello_ver": None,
    }
    dev = open_pid(0x9008)
    if dev is None:
        log("  9008 disappeared before upload")
        return res
    link = Link(dev)

    pkt = link.read_packet(5000)
    if pkt is None:
        log("  no HELLO on 9008")
        return res
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd == CMD_END_TRANSFER:
        # clear a stale transfer, then re-read
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        pkt = link.read_packet(4000)
        if pkt is None:
            return res
        cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO, got {cmd:#x}")
        return res

    ver = struct.unpack_from("<I", pkt, 8)[0]
    res["hello_ver"] = ver
    log(f"  HELLO ver={ver} mode={struct.unpack_from('<I', pkt, 20)[0]}")
    link.write(hello_rsp(ver, MODE_IMAGE_TX))

    sent = 0
    reads = 0
    while True:
        pkt = link.read_packet(8000)
        if pkt is None:
            log(f"  timeout after {sent} B")
            break
        cmd = struct.unpack_from("<I", pkt, 0)[0]

        if cmd == CMD_READ_DATA:
            img, off, dlen = struct.unpack_from("<III", pkt, 8)
        elif cmd == CMD_READ_DATA_64:
            img, off, dlen = struct.unpack_from("<IQQ", pkt, 8)
        else:
            if cmd == CMD_END_TRANSFER:
                status = struct.unpack_from("<I", pkt, 12)[0] if len(pkt) >= 16 else -1
                res["end_status"] = status
                res["end_at"] = time.time()
                log(f"  END status={status:#x} after {sent} B in {reads} reads")
            else:
                log(f"  stop on cmd {cmd:#x} after {sent} B")
            break

        chunk = payload[off:off + dlen]
        if len(chunk) < dlen:
            # Short payload: the device is asking for an offset past the end of
            # what we gave it. Log it rather than padding blindly - a huge dlen
            # here would otherwise allocate for no reason.
            log(f"    READ[{reads + 1}] off={off} len={dlen} "
                f"-> PAST END of payload ({len(payload)} B); "
                f"{dlen - len(chunk)} B missing")
            if dlen > (32 << 20):
                log("    refusing to pad an implausible length")
                break
            chunk += b"\xff" * (dlen - len(chunk))
        link.write(chunk)
        sent += len(chunk)
        reads += 1
        if reads <= 8 or reads % 10 == 0:
            log(f"    READ[{reads}] off={off} len={dlen} total={sent}")

    res["sent"] = sent
    res["reads"] = reads

    if res["end_status"] == 0 and sent >= MIN_PLAUSIBLE:
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        r = link.read_packet(4000)
        if r is not None:
            res["done_at"] = time.time()
            res["ok"] = True
            log(f"  DONE -> cmd={struct.unpack_from('<I', r, 0)[0]:#x}  (upload ok)")
    elif res["end_status"] == 0:
        log("  END 0x0 but transfer too short - refusing to call it success")

    return res


def watch_after_done(seconds: float = 26.0) -> list[tuple[float, str]]:
    """Poll USB state tightly and record only transitions."""
    transitions = []
    last = None
    start = time.time()
    while time.time() - start < seconds:
        if find(0x9008) is not None:
            state = "9008"
        elif find(0x900E) is not None:
            state = "900E"
        else:
            state = "absent"
        if state != last:
            transitions.append((time.time() - start, state))
            last = state
        time.sleep(0.02)
    return transitions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--watch", type=float, default=26.0)
    args = ap.parse_args()

    path = Path(args.payload)
    if not path.is_file():
        log(f"payload not found: {path}")
        return 2
    payload = path.read_bytes()
    label = args.label or path.name

    log("=" * 74)
    log(f"#  upload_compare - payload '{label}'  ({len(payload)} B)")
    log(f"#  file: {path}")
    log("=" * 74)

    if not bump_to_9008():
        log(">>> could not reach 9008")
        return 1

    # A previously aborted upload leaves a node that is present but mute. Wait
    # for a genuinely fresh 9008 (device must have left the bus and come back).
    res = None
    for attempt in range(1, 4):
        res = upload(payload, label)
        if res["ok"] or res["sent"] > 0:
            break
        log(f"  attempt {attempt}: node present but mute - waiting for a power cycle")
        end = time.time() + 70
        while time.time() < end and (find(0x9008) is not None or find(0x900E) is not None):
            time.sleep(0.05)
        if not bump_to_9008():
            log(">>> lost the device")
            return 1

    if not res["ok"]:
        log("")
        log(f"  upload did not complete: END={res['end_status']} sent={res['sent']}")
        return 1

    log("")
    log(f"  watching for {args.watch:.0f} s from DONE (20 ms poll)")
    tr = watch_after_done(args.watch)
    for dt, state in tr:
        log(f"    +{dt:6.3f}s  -> {state}")

    left = [dt for dt, st in tr if st == "absent"]
    if left:
        log("")
        log(f"  first absence at +{left[0]:.3f}s after DONE")
        back = [dt for dt, st in tr if st == "900E"]
        if back:
            log(f"  back as crashdump at +{back[0]:.3f}s "
                f"(absent for {back[0] - left[0]:.3f}s)")
    else:
        log("")
        log("  device never left the bus during the watch window")

    log("")
    log("=" * 74)
    log("#  RESULT")
    log("=" * 74)
    log(f"  payload      : {label} ({len(payload)} B)")
    log(f"  END status   : {res['end_status']}")
    log(f"  bytes sent   : {res['sent']}")
    log(f"  reads        : {res['reads']}")
    log(f"  first absent : +{left[0]:.3f}s" if left else "  first absent : never")
    return 0


if __name__ == "__main__":
    sys.exit(main())
