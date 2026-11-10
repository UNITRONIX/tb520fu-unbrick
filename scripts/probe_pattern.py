#!/usr/bin/env python3
"""probe_pattern.py - what exactly makes the node go mute after one read?

The contradiction to resolve
----------------------------
check_tablet.py gets a HELLO. Seconds later reset_culprit.py does not, on the same
node, with no other process touching it. That is not a device fault pattern - it is a
pattern that depends on what the previous read did.

This script does the boring, decisive thing: it tries a fresh HELLO probe repeatedly,
logging the state between attempts, so the point where the node stops answering can be
seen directly instead of inferred.

No resets are sent. Each attempt opens the node, reads one packet with a short
timeout, and releases the interface. If the node survives that, the problem is in the
more elaborate close paths; if it does not, the read itself is what wedges it.

Read-only.

Usage
    python probe_pattern.py --attempts 6
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

T0 = time.time()


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def present() -> tuple[bool, int | None, int | None]:
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    if dev is None:
        return False, None, None
    return True, dev.bus, dev.address


def one_probe(label: str) -> str:
    """Open, read one packet, release. Returns a one-word outcome."""
    ok, bus, addr = present()
    if not ok:
        return "absent"

    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    try:
        dev.set_configuration(1)
    except usb.core.USBError as err:
        return f"cfg-fail({err.errno})"
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError as err:
        return f"claim-fail({err.errno})"

    cfg = dev.get_active_configuration()
    ep_in = usb.util.find_descriptor(
        cfg[(0, 0)],
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_IN)
    try:
        raw = ep_in.read(0x10000, 2000)
        raw = bytes(raw)
        if len(raw) >= 4:
            cmd = struct.unpack_from("<I", raw, 0)[0]
            return f"HELLO(cmd={cmd:#x})"
        return "short-read"
    except usb.core.USBTimeoutError:
        return "timeout"
    except usb.core.USBError as err:
        return f"usb-err({err.errno})"
    finally:
        # Release WITHOUT sending anything. This is the gentlest possible close, so
        # that if the node wedges anyway the read is implicated rather than a reset.
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--gap", type=float, default=2.0)
    args = ap.parse_args()

    print("=" * 70)
    print("#  repeated bare HELLO probes, no resets sent")
    print("=" * 70)

    results = []
    for i in range(args.attempts):
        ok, bus, addr = present()
        state = f"present bus{bus} addr{addr}" if ok else "absent"
        outcome = one_probe(f"attempt{i}")
        log(f"  attempt {i + 1}: {state:<24} -> {outcome}")
        results.append(outcome)
        time.sleep(args.gap)

    print()
    print("=" * 70)
    print("#  RESULT")
    print("=" * 70)
    hello = sum(1 for r in results if r.startswith("HELLO"))
    timeouts = sum(1 for r in results if r == "timeout")
    absent = sum(1 for r in results if r == "absent")
    log(f"  HELLO: {hello}   timeout: {timeouts}   absent: {absent}")
    print()

    if hello == len(results):
        print("  The node answers every bare probe. Reading one packet and releasing")
        print("  the interface does NOT wedge it, so the problem is in the more")
        print("  elaborate close path - a SAHARA_RESET, or a read left outstanding.")
    elif hello > 0 and timeouts > 0:
        print("  The node answered some probes and not others. That is the pattern")
        print("  seen between check_tablet and reset_culprit. Because this run sends")
        print("  NO reset, the variable is not the reset - it is either the")
        print("  enumeration timing or the fact that a previous read consumed the")
        print("  HELLO that the next one expects.")
        print()
        print("  Note the second explanation: Sahara HELLO is a single pending")
        print("  packet. Whoever reads it consumes it. If the previous session left")
        print("  the state machine advanced, the next open legitimately sees nothing.")
        print("  That would mean 'mute' is often not mute at all - just mid-state.")
    elif absent == len(results):
        print("  The node never appeared. Try again during an enumeration window.")
    else:
        print("  The node was mute from the first probe. It is genuinely wedged and")
        print("  needs a power cycle.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
