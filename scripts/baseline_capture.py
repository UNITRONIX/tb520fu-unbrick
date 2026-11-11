#!/usr/bin/env python3
"""baseline_capture.py - take clean captures with proper handle disposal.

Why this exists separately
--------------------------
upload_fingerprint.py does the whole experiment, but it needs a reliable baseline
first. The previous attempt failed because a libusb claim was leaked between captures
(EACCES on the second open), which looked like a device fault and stalled the run.

This takes N captures with `dispose_resources` on every path, verifies each one
succeeded, and reports how much the device varies on its own. That variation is the
threshold any upload-induced change must exceed to mean anything.

Read-only.

Usage
    python baseline_capture.py --samples 3
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
    CMD_HELLO_REQ,
    CMD_HELLO_RSP,
    CMD_MEMORY_DEBUG,
    CMD_MEMORY_DEBUG_64,
    Link,
    mem_read,
)

OUT = Path(__file__).resolve().parent / "baseline"
T0 = time.time()

REGIONS = [
    (0x14680000, 0x1000, "OCIMEM"),
    (0x81B75000, 0x1000, "PMIC"),
    (0x24020000, 0x1000, "SHRM"),
]
MODE_MEMORY_DEBUG = 2


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def one_capture(tries: int = 5) -> dict | None:
    """Open, handshake, read the regions, dispose. Retries across cycles."""
    for attempt in range(tries):
        dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
        if dev is None:
            time.sleep(0.5)
            continue

        link = None
        try:
            dev.set_configuration(1)
        except usb.core.USBError:
            pass
        try:
            usb.util.claim_interface(dev, 0)
        except usb.core.USBError as err:
            # The classic leaked-claim symptom. Dispose and retry.
            log(f"    attempt {attempt + 1}: claim failed ({err.errno})")
            try:
                usb.util.dispose_resources(dev)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
            continue

        try:
            link = Link(dev)
            pkt = link.read_packet(2500)
            if pkt is None:
                raise RuntimeError("no HELLO")
            cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd != CMD_HELLO_REQ:
                raise RuntimeError(f"expected HELLO, got {cmd:#x}")

            ver = struct.unpack_from("<I", pkt, 8)[0]
            mode = struct.unpack_from("<I", pkt, 20)[0]
            if mode != MODE_MEMORY_DEBUG:
                raise RuntimeError(f"mode {mode} is not crashdump")

            link.write(struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                                   ver, 1, 0, MODE_MEMORY_DEBUG,
                                   1, 2, 3, 4, 5, 6))
            rsp = link.read_packet(4000)
            if rsp is None:
                raise RuntimeError("no MEMORY_DEBUG reply")
            rcmd = struct.unpack_from("<I", rsp, 0)[0]
            if rcmd == CMD_MEMORY_DEBUG:
                tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
            elif rcmd == CMD_MEMORY_DEBUG_64:
                tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
            else:
                raise RuntimeError(f"unexpected cmd {rcmd:#x}")

            out = {}
            for addr, ln, name in REGIONS:
                blob = mem_read(link, addr, ln, tmo=8.0)
                if blob:
                    out[name] = blob
            if not out:
                raise RuntimeError("no regions read")
            return out
        except Exception as err:  # noqa: BLE001
            log(f"    attempt {attempt + 1}: {type(err).__name__} {err}")
            time.sleep(1.0)
        finally:
            try:
                usb.util.release_interface(dev, 0)
            except Exception:  # noqa: BLE001
                pass
            try:
                usb.util.dispose_resources(dev)
            except Exception:  # noqa: BLE001
                pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--gap", type=float, default=3.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    print("=" * 72)
    print(f"#  baseline capture, {args.samples} samples")
    print("=" * 72)

    samples = []
    for i in range(args.samples):
        log(f"sample {i + 1}")
        s = one_capture()
        if s is None:
            log("  FAILED to capture")
            continue
        samples.append(s)
        h = {k: hashlib.sha256(v).hexdigest()[:16] for k, v in s.items()}
        log(f"  {h}")
        for k, v in s.items():
            (OUT / f"s{i}_{k}.bin").write_bytes(v)
        time.sleep(args.gap)

    if len(samples) < 2:
        log("")
        log("only one capture succeeded - cannot establish natural variation")
        return 1

    print()
    print("=" * 72)
    print("#  natural variation (the threshold any real change must exceed)")
    print("=" * 72)

    for _, _, name in REGIONS:
        blobs = [s[name] for s in samples if name in s]
        if len(blobs) < 2:
            continue
        n = min(len(b) for b in blobs)
        pair_diffs = []
        for i in range(len(blobs) - 1):
            d = sum(1 for k in range(n) if blobs[i][k] != blobs[i + 1][k])
            pair_diffs.append(d)
        same = len(set(hashlib.sha256(b).hexdigest() for b in blobs)) == 1
        log(f"  {name:<8} differing bytes between consecutive captures: {pair_diffs}"
            + ("   (identical)" if same else ""))

    print()
    print("  Any post-upload difference must be LARGER than these numbers to be")
    print("  attributable to the programmer rather than to ordinary boot variation.")
    (OUT / "baseline.json").write_text(json.dumps(
        [{k: hashlib.sha256(v).hexdigest() for k, v in s.items()} for s in samples],
        indent=2))
    log(f"  saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
