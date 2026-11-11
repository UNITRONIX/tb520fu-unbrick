#!/usr/bin/env python3
"""fingerprint_v2.py - the upload-fingerprint experiment, done correctly.

The corrected model
-------------------
The tablet does not boot-loop. Left alone it waits in 900E; it only leaves when
something sends it a Sahara command. So the sequence is:

    900E  ->  bump to 9008  ->  upload programmer  ->  device returns to 900E
          ->  capture  ->  compare against a baseline captured before the upload

No waiting for absences, no assuming cycles. See docs/23-no-boot-loop.md.

What is measured
----------------
The crash dump exposes OCIMEM, which holds boot-ROM working state and demonstrably
varies between boots. If the programmer runs at all, it must touch something. A region
that differs MORE after an upload than it does between two idle captures is the
programmer's fingerprint.

That comparison only means anything with a baseline-to-baseline reference, so this
takes two captures before the upload as well as one after.

Read-only apart from the upload itself, which loads a programmer into RAM - the same
operation every earlier attempt performed. It does not write storage.

Usage
    python fingerprint_v2.py --melf <ROM>/image/xbl_s_devprg_ns.melf
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
    Link,
    mem_read,
)

OUT = Path(__file__).resolve().parent / "fingerprint_v2"
T0 = time.time()

REGIONS = [
    (0x14680000, 0x1000, "OCIMEM"),
    (0x81B75000, 0x1000, "PMIC"),
    (0x24020000, 0x1000, "SHRM"),
]

MODE_COMMAND = 3
MODE_IMAGE_TX = 0
MODE_MEMORY_DEBUG = 2
MIN_SENT = 1_500_000


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
def bump_to_9008(tries: int = 3) -> bool:
    """900E -> 9008 using the documented mode switch."""
    if pid() == 0x9008:
        return True

    for attempt in range(tries):
        dev = open_dev(0x900E)
        if dev is None:
            time.sleep(0.5)
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
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                pkt = link.read_packet(2500)
                if pkt is None:
                    raise RuntimeError("no HELLO after END")
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
                link.write(struct.pack("<III", 0x0C, 12, MODE_IMAGE_TX))
                r = link.read_packet(4000)
                if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
                    raise RuntimeError("switch not confirmed")
                link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
                r = link.read_packet(4000)
                if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
                    link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                    link.read_packet(2000)
            log("  bump: switched")
        except Exception as err:  # noqa: BLE001
            log(f"  bump attempt {attempt + 1}: {type(err).__name__} {err}")
            continue
        finally:
            close_dev(dev)

        end = time.time() + 45
        while time.time() < end:
            if pid() == 0x9008:
                time.sleep(0.2)
                return True
            time.sleep(0.1)
    return False


def capture_regions() -> dict | None:
    """Read the regions from 900E in one session."""
    dev = open_dev(0x900E)
    if dev is None:
        log("  900E not openable")
        return None
    try:
        link = Link(dev)
        pkt = link.read_packet(2500)
        if pkt is None:
            log("  no HELLO")
            return None
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO, got {cmd:#x}")
            return None
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        if mode != MODE_MEMORY_DEBUG:
            log(f"  mode {mode} is not crashdump")
            return None
        link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = link.read_packet(4000)
        if rsp is None:
            return None
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
            return None

        out = {}
        for addr, ln, name in REGIONS:
            blob = mem_read(link, addr, ln, tmo=8.0)
            if blob:
                out[name] = blob
        return out or None
    finally:
        close_dev(dev)


def do_upload(payload: bytes) -> str:
    if not bump_to_9008():
        return "could not reach 9008"
    dev = open_dev(0x9008)
    if dev is None:
        return "9008 not openable"
    try:
        link = Link(dev)
        pkt = link.read_packet(5000)
        if pkt is None:
            return "no HELLO on 9008"
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
            cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd == CMD_READ_DATA:
                _i, off, dlen = struct.unpack_from("<III", pkt, 8)
            elif cmd == 0x12:
                _i, off, dlen = struct.unpack_from("<IQQ", pkt, 8)
            elif cmd == CMD_END_TRANSFER:
                status = struct.unpack_from("<I", pkt, 12)[0] if len(pkt) >= 16 else -1
                break
            else:
                status = f"cmd {cmd:#x}"
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
        return f"end={status} sent={sent}"
    finally:
        close_dev(dev)


# ---------------------------------------------------------------------------
def diff(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] != b[i])


def return_to_900e(tries: int = 3) -> bool:
    """Get the device back to 900E so the crash dump is readable.

    After a bump the device sits at 9008. A SAHARA_RESET at 9008 makes it leave and
    come back as 900E within a few seconds, which is the state the memory table is
    served from.
    """
    if pid() == 0x900E:
        return True
    if pid() is None:
        # nothing present: it is between states, wait for either
        end = time.time() + 30
        while time.time() < end and pid() is None:
            time.sleep(0.2)

    for attempt in range(tries):
        if pid() == 0x900E:
            return True
        if pid() == 0x9008:
            dev = open_dev(0x9008)
            if dev is not None:
                try:
                    link = Link(dev)
                    pkt = link.read_packet(2500)
                    if pkt is not None:
                        cmd = struct.unpack_from("<I", pkt, 0)[0]
                        if cmd == CMD_HELLO_REQ:
                            ver = struct.unpack_from("<I", pkt, 8)[0]
                            link.write(hello_rsp(ver, MODE_IMAGE_TX))
                    link.write(struct.pack("<II", CMD_RESET, 8))
                    link.read_packet(1500)
                    log("  sent SAHARA_RESET at 9008")
                except Exception as err:  # noqa: BLE001
                    log(f"  reset attempt {attempt + 1}: {type(err).__name__}")
                finally:
                    close_dev(dev)

        end = time.time() + 40
        while time.time() < end:
            if pid() == 0x900E:
                time.sleep(0.3)
                return True
            time.sleep(0.2)
    return pid() == 0x900E


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", required=True)
    args = ap.parse_args()

    path = Path(args.melf)
    if not path.is_file():
        log(f"not found: {path}")
        return 2
    payload = path.read_bytes()
    log(f"payload {path.name}  {len(payload)} B")

    OUT.mkdir(exist_ok=True)
    log(f"current state: {pid():04x}" if pid() else "no device")

    # The baseline needs 900E. If a previous bump left the device at 9008, reset it.
    if pid() != 0x900E:
        log("returning to 900E for the baseline")
        if not return_to_900e():
            log("  could not get back to 900E")
            return 1

    # ---- baseline: two captures, no upload in between --------------------
    log("")
    log("=== BASELINE 1 ===")
    b1 = capture_regions()
    if b1 is None:
        log("  failed")
        return 1
    log(f"  {[f'{k}:{hashlib.sha256(v).hexdigest()[:12]}' for k, v in b1.items()]}")

    log("")
    log("=== BASELINE 2 (same conditions, no upload) ===")
    time.sleep(2)
    b2 = capture_regions()
    if b2 is None:
        log("  failed")
        return 1
    log(f"  {[f'{k}:{hashlib.sha256(v).hexdigest()[:12]}' for k, v in b2.items()]}")

    print()
    log("natural variation (baseline1 vs baseline2):")
    natural = {}
    for _, _, name in REGIONS:
        if name in b1 and name in b2:
            natural[name] = diff(b1[name], b2[name])
            log(f"  {name:<8} {natural[name]} bytes differ")

    # ---- the upload ------------------------------------------------------
    log("")
    log("=== UPLOAD ===")
    status = do_upload(payload)
    log(f"  result: {status}")

    # ---- after -----------------------------------------------------------
    log("")
    log("=== AFTER (device should return to 900E by itself) ===")
    end = time.time() + 60
    while time.time() < end and pid() != 0x900E:
        time.sleep(0.2)
    log(f"  state now: {pid():04x}" if pid() else "  no device")
    after = capture_regions()
    if after is None:
        log("  capture failed")
        return 1
    log(f"  {[f'{k}:{hashlib.sha256(v).hexdigest()[:12]}' for k, v in after.items()]}")

    # ---- verdict ---------------------------------------------------------
    print()
    print("=" * 74)
    print("#  RESULT")
    print("=" * 74)
    log(f"  upload: {status}")
    log("")
    log(f"  {'region':<8} {'natural':>8} {'after upload':>14}  verdict")
    log("  " + "-" * 52)
    for _, _, name in REGIONS:
        if name not in b1 or name not in after:
            continue
        nat = natural.get(name, 0)
        aft = diff(b1[name], after[name])
        verdict = "EXCEEDS natural" if aft > nat else "within natural"
        log(f"  {name:<8} {nat:>8} {aft:>14}  {verdict}")

    print()
    print("  A region whose post-upload difference exceeds its natural variation")
    print("  was touched by the programmer. That is the fingerprint.")

    (OUT / "fingerprint.json").write_text(json.dumps({
        "upload": status,
        "hashes": {
            "before1": {k: hashlib.sha256(v).hexdigest() for k, v in b1.items()},
            "before2": {k: hashlib.sha256(v).hexdigest() for k, v in b2.items()},
            "after": {k: hashlib.sha256(v).hexdigest() for k, v in after.items()},
        },
        "natural": natural,
    }, indent=2))
    for tag, s in (("b1", b1), ("b2", b2), ("after", after)):
        for k, v in s.items():
            (OUT / f"{tag}_{k}.bin").write_bytes(v)
    log(f"  saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
