#!/usr/bin/env python3
"""upload_fingerprint.py - does a failed programmer run leave a trace?

The experiment
--------------
Measured facts:
  - an idle boot loop produces byte-identical scalar registers every time;
  - OCIMEM (0x14680000, 4 KiB window) differs between idle boots in 2551 of 4096
    bytes, so it carries live boot state;
  - the programmer is accepted by Sahara (END 0x00, DONE), then goes silent.

If the programmer runs at all, it must touch memory. So a capture taken immediately
after a failed upload should differ from an idle capture in ways an idle capture never
differs from another idle capture.

Method
------
  baseline : N captures of the idle boot loop
  trigger  : one Sahara upload of the melf, exactly as previous attempts did
  after    : N captures as soon as the device returns to 900E

Then compare "baseline vs baseline" against "baseline vs after". The first establishes
how much the device varies on its own. The second shows whether the upload adds
anything beyond that.

Without the baseline-vs-baseline comparison, any difference would be meaningless - the
regions already vary between ordinary boots.

This uploads a programmer into RAM. That does not write storage. It is the same
operation every earlier attempt performed.

Usage
    python upload_fingerprint.py --melf <ROM>/image/xbl_s_devprg_ns.melf
    python upload_fingerprint.py --melf ... --samples 2
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
    CMD_READ_DATA,
    CMD_RESET,
    Link,
    handshake_memory_debug,
    mem_read,
    open_device,
)

OUT = Path(__file__).resolve().parent / "upload_fingerprint"
T0 = time.time()

REGIONS = [
    (0x14680000, 0x1000, "OCIMEM"),
    (0x81B75000, 0x1000, "PMIC"),
    (0x24020000, 0x1000, "SHRM"),
]

MODE_IMAGE_TX = 0
MODE_COMMAND = 3
MIN_SENT = 1_500_000


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


# ---------------------------------------------------------------------------
def qcom_pid() -> int | None:
    for p in (0x900E, 0x9008):
        if usb.core.find(idVendor=0x05C6, idProduct=p) is not None:
            return p
    return None


def wait_for_900e(budget: float = 120.0) -> bool:
    end = time.time() + budget
    while time.time() < end:
        if qcom_pid() == 0x900E:
            time.sleep(0.1)
            return True
        time.sleep(0.05)
    return False


def capture(budget: float = 200.0, tries: int = 4) -> dict | None:
    """Take one capture, retrying across boot cycles.

    A boot-looping unit is absent for ~15 s at a time, so a single attempt can miss
    entirely. Each try waits for a fresh 900E and then attempts the handshake.
    """
    for attempt in range(tries):
        end = time.time() + budget / tries
        link = tables = None
        while time.time() < end:
            if qcom_pid() != 0x900E:
                time.sleep(0.05)
                continue
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
            # let it cycle before the next attempt
            end2 = time.time() + 60
            while time.time() < end2 and qcom_pid() is not None:
                time.sleep(0.05)
        if not tables:
            log(f"    capture attempt {attempt + 1}/{tries}: no session")
            continue

        out = {}
        for addr, ln, name in REGIONS:
            blob = mem_read(link, addr, ln, tmo=8.0)
            if blob:
                out[name] = blob

        # Close the session cleanly. Without this the node is left mid-handshake and
        # the next open can block or fail, which presents as a mystery "no session"
        # on a perfectly healthy device.
        try:
            link.write(struct.pack("<II", CMD_RESET, 8))
            link.read_packet(1500)
        except Exception:  # noqa: BLE001
            pass

        if out:
            return out
    return None


# ---------------------------------------------------------------------------
def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def bump_if_needed(tries: int = 3) -> bool:
    """Get to 9008 from 900E using the documented switch.

    The device resets frequently, so opening the node can fail with 'Access denied'
    mid-enumeration. Each try waits for a stable 900E first.
    """
    if qcom_pid() == 0x9008:
        return True

    for attempt in range(tries):
        if qcom_pid() != 0x900E:
            end = time.time() + 45
            while time.time() < end and qcom_pid() != 0x900E:
                time.sleep(0.05)
            if qcom_pid() != 0x900E:
                continue

        dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
        if dev is None:
            continue
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
        except Exception as err:  # noqa: BLE001
            log(f"    bump attempt {attempt + 1}: open failed ({type(err).__name__})")
            time.sleep(1.0)
            continue

        try:
            pkt = link.read_packet(2500)
            if pkt is None:
                link.write(struct.pack("<II", CMD_RESET, 8))
                pkt = link.read_packet(2500)
            if pkt is None:
                continue
            cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd == CMD_END_TRANSFER:
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                pkt = link.read_packet(2500)
                if pkt is None:
                    continue
                cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd != CMD_HELLO_REQ:
                continue
            ver = struct.unpack_from("<I", pkt, 8)[0]
            mode = struct.unpack_from("<I", pkt, 20)[0]
            if mode == MODE_IMAGE_TX:
                return True
            link.write(hello_rsp(ver, MODE_COMMAND))
            r = link.read_packet(3000)
            if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
                continue
            link.write(struct.pack("<III", 0x0C, 12, MODE_IMAGE_TX))
            r = link.read_packet(4000)
            if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
                continue
            link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
            r = link.read_packet(4000)
            if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                link.read_packet(2000)
        except Exception as err:  # noqa: BLE001
            log(f"    bump attempt {attempt + 1}: {type(err).__name__}")
            continue

        end = time.time() + 45
        while time.time() < end:
            if qcom_pid() == 0x9008:
                time.sleep(0.1)
                return True
            time.sleep(0.05)
    return False


def do_upload(payload: bytes) -> str:
    """Perform the same upload every previous attempt performed. Returns a status."""
    if not bump_if_needed():
        return "could not reach 9008"
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x9008)
    if dev is None:
        return "9008 disappeared"
    try:
        dev.set_configuration(1)
    except usb.core.USBError:
        pass
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError:
        pass
    link = Link(dev)

    pkt = link.read_packet(5000)
    if pkt is None:
        return "no HELLO on 9008"
    ver = struct.unpack_from("<I", pkt, 8)[0]
    link.write(hello_rsp(ver, MODE_IMAGE_TX))

    sent = 0
    reads = 0
    status = None
    while True:
        pkt = link.read_packet(8000)
        if pkt is None:
            status = f"timeout after {sent} B"
            break
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd == CMD_READ_DATA:
            _img, off, dlen = struct.unpack_from("<III", pkt, 8)
        elif cmd == 0x12:  # SAHARA_READ_DATA_64
            _img, off, dlen = struct.unpack_from("<IQQ", pkt, 8)
        elif cmd == CMD_END_TRANSFER:
            status = struct.unpack_from("<I", pkt, 12)[0] if len(pkt) >= 16 else -1
            break
        else:
            status = f"unexpected cmd {cmd:#x}"
            break
        chunk = payload[off:off + dlen]
        if len(chunk) < dlen:
            chunk += b"\xff" * (dlen - len(chunk))
        link.write(chunk)
        sent += len(chunk)
        reads += 1

    log(f"    upload: END={status} sent={sent} reads={reads}")
    if status == 0 and sent >= MIN_SENT:
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        link.read_packet(3000)
        log("    DONE acknowledged")
    return f"end={status} sent={sent}"


# ---------------------------------------------------------------------------
def hashes(samples: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in samples:
        for name, blob in s.items():
            out.setdefault(name, []).append(hashlib.sha256(blob).hexdigest()[:16])
    return out


def diff_bytes(a: dict, b: dict, name: str) -> int:
    if name not in a or name not in b:
        return -1
    ba, bb = a[name], b[name]
    n = min(len(ba), len(bb))
    return sum(1 for i in range(n) if ba[i] != bb[i])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", required=True)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--delay", type=float, default=20.0)
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        log(f"melf not found: {path}")
        return 2
    payload = path.read_bytes()
    log(f"payload: {path.name}  {len(payload)} B")

    OUT.mkdir(exist_ok=True)

    # ---- baseline -------------------------------------------------------
    log("")
    log("=== BASELINE: idle boot loop ===")
    baseline = []
    for i in range(args.samples):
        wait_for_900e()
        s = capture()
        if s:
            baseline.append(s)
            h = {k: hashlib.sha256(v).hexdigest()[:16] for k, v in s.items()}
            log(f"  baseline[{i}]: {h}")
        if i + 1 < args.samples:
            time.sleep(args.delay)

    if len(baseline) < 2:
        log("need two baseline captures to know how much the device varies on its own")
        return 1

    # ---- trigger --------------------------------------------------------
    log("")
    log("=== TRIGGER: one programmer upload (same as every previous attempt) ===")
    status = do_upload(payload)
    log(f"  result: {status}")

    # ---- after ----------------------------------------------------------
    log("")
    log("=== AFTER: capture as soon as the device returns ===")
    after = []
    for i in range(args.samples):
        if not wait_for_900e(150):
            log("  device did not return as 900E")
            break
        s = capture()
        if s:
            after.append(s)
            h = {k: hashlib.sha256(v).hexdigest()[:16] for k, v in s.items()}
            log(f"  after[{i}]: {h}")
        if i + 1 < len(range(args.samples)):
            time.sleep(args.delay)

    # ---- comparison -----------------------------------------------------
    print()
    print("=" * 74)
    print("#  RESULT")
    print("=" * 74)

    log("baseline vs baseline (natural variation):")
    base_diffs = {}
    for name, _, _ in REGIONS:
        vals = [diff_bytes(baseline[i], baseline[i + 1], name)
                for i in range(len(baseline) - 1)]
        base_diffs[name] = vals
        log(f"  {name:<8} differing bytes: {vals}")

    if not after:
        log("")
        log("no post-upload captures - the device did not come back")
        return 1

    log("")
    log("baseline vs after (does the upload add anything?):")
    for name, _, _ in REGIONS:
        vals = [diff_bytes(baseline[0], a, name) for a in after]
        natural = max(base_diffs.get(name, [0])) if base_diffs.get(name) else 0
        extra = max(vals) > natural
        log(f"  {name:<8} differing bytes: {vals}   "
            f"(natural max {natural}){'   <-- EXCEEDS natural' if extra else ''}")

    print()
    print("  Interpretation: if a region differs after the upload by MORE than the")
    print("  device manages on its own, the programmer touched it. That is the")
    print("  fingerprint, and it would be the first direct evidence of what the")
    print("  failed run actually did.")

    (OUT / "result.json").write_text(json.dumps({
        "baseline_hashes": hashes(baseline),
        "after_hashes": hashes(after),
        "upload": status,
    }, indent=2))
    log(f"  written to {OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
