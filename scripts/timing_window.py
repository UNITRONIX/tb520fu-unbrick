#!/usr/bin/env python3
"""timing_window.py - how long after enumeration does the node answer?

What the probes showed
----------------------
probe_pattern.py ran six bare HELLO probes two seconds apart against a present node:

    attempt 1  timeout
    attempt 2  cfg-fail(13)   Access denied
    attempt 3  cfg-fail(13)
    ...
    attempt 6  cfg-fail(13)

and earlier, check_tablet.py had got a HELLO on the same node seconds before. So the
node answers in a narrow window and then stops being openable at all - and the
`cfg-fail(13)` persists even though nothing was sent to it.

That is not a Sahara state issue: Access-denied is a *host-side* open failure, meaning
the device handle is held or the interface cannot be claimed. Two candidates:

  a) enumeration churn - the node re-enumerates and the OS has not settled the
     permissions yet;
  b) a leaked handle from an earlier process in this session.

This script distinguishes them by logging, for each moment in a boot cycle, whether
the node is present and whether it can be opened and read - at high resolution, from a
single process that never holds a handle between attempts.

Read-only.

Usage
    python timing_window.py --seconds 90
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

T0 = time.time()


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def snapshot():
    """Return (present, openable, readable) for one instant."""
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    if dev is None:
        return False, False, False, 0

    try:
        dev.set_configuration(1)
    except usb.core.USBError as err:
        return True, False, False, err.errno or 0
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError as err:
        return True, False, False, err.errno or 0

    read_ok = False
    try:
        cfg = dev.get_active_configuration()
        ep = usb.util.find_descriptor(
            cfg[(0, 0)],
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN)
        raw = bytes(ep.read(0x10000, 400))
        read_ok = len(raw) >= 4
    except Exception:  # noqa: BLE001
        read_ok = False
    finally:
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        # Dispose the handle, or the NEXT snapshot fails with EACCES (errno 13) and
        # is counted as "present but not openable". Without this the measurement is
        # dominated by the tool's own leaked claims rather than by the device, which
        # is how an earlier run reported 490/491 "not openable" for a healthy node.
        try:
            usb.util.dispose_resources(dev)
        except Exception:  # noqa: BLE001
            pass

    return True, True, read_ok, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0)
    args = ap.parse_args()

    print("=" * 70)
    print(f"#  sampling node openability for {args.seconds:.0f}s")
    print("=" * 70)
    print("  legend: P=present O=openable R=readable")

    last = None
    counts = {"absent": 0, "present-noopen": 0, "open-noREAD": 0, "READ": 0}
    transitions = []
    end = time.time() + args.seconds

    while time.time() < end:
        present, openable, readable, err = snapshot()

        if not present:
            state = "absent"
        elif not openable:
            state = f"present-noopen(err{err})"
        elif not readable:
            state = "open-noREAD"
        else:
            state = "READ"

        key = ("absent" if state == "absent"
               else "present-noopen" if state.startswith("present-noopen")
               else "open-noREAD" if state == "open-noREAD"
               else "READ")
        counts[key] += 1

        if state != last:
            transitions.append((time.time() - T0, state))
            log(f"  {state}")
            last = state
        time.sleep(0.15)

    print()
    print("=" * 70)
    print("#  RESULT")
    print("=" * 70)
    total = sum(counts.values())
    for k, v in counts.items():
        log(f"  {k:<16} {v:>5} samples  ({v / total * 100:.1f}%)")

    log("")
    log("  transitions:")
    for t, s in transitions:
        log(f"    +{t:6.2f}s  {s}")

    print()
    if counts["READ"] == 0:
        print("  The node was never readable. Either it is wedged, or it never")
        print("  finished a handshake it had already started before this run.")
        print("  A power cycle is the only remedy; running this immediately after")
        print("  the device reappears is the useful experiment.")
    elif counts["absent"] > 0 and counts["READ"] > 0:
        print("  The node is readable only during part of each boot cycle. That is")
        print("  expected: it is absent ~15 s, enumerates, then boots on and resets.")
        print(f"  Readable in {counts['READ']} of {total} samples, so a capture must")
        print("  land inside the window - which the retry logic now does.")
    else:
        print("  The node stayed readable throughout this window.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
