#!/usr/bin/env python3
"""short_attempt.py - guide and record the D+ short attempt, both plug orientations.

Why a dedicated script
---------------------
A USB-C cable carries only ONE USB 2.0 pair, and which receptacle contact it reaches
depends on plug orientation (A6/B6 or A7/B7 - see docs/93). So "hold the short and plug
it in" has to be tried TWICE, once each way up, and the results compared. Doing that from
memory across two physical attempts is how a real signal gets dismissed as noise.

This script:
  - prompts for one orientation at a time
  - watches for the device leaving and returning, with no VID filter
  - records which orientation produced which PID
  - tells you plainly whether to flip the plug and try again

Read-only: it enumerates USB and, if a Qualcomm port appears, reads one packet.

Usage
    python short_attempt.py --orientation A
    python short_attempt.py --orientation B
    python short_attempt.py --summary
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ab_test import classify, tablet_nodes, usb_nodes  # noqa: E402
import tablet as T  # noqa: E402  - the one place that knows how to read a HELLO

OUT = HERE / "short_attempt.json"


def log(m: str = "") -> None:
    print(m, flush=True)


def read_port() -> str:
    """Read the HELLO if a Qualcomm COM port exists, and CAPTURE it.

    Delegates to tablet.grab_edl_hello rather than doing its own 64-byte read.
    Two reasons, both learned the hard way in this project:

      * a bare `read(64)` is not a packet - a Sahara HELLO is 0x30 bytes and a partial
        read makes the version/mode fields look wrong;
      * the capture is written to disk by tablet.save_hello_capture, which is the only
        way this measurement survives the session (docs/97, docs/102).
    """
    return T.grab_any_hello(8.0)


def run(orientation: str, seconds: float) -> int:
    log("=" * 74)
    log(f"#  D+ short attempt - plug orientation {orientation.upper()}")
    log("=" * 74)
    log("")
    log("  Prepare first:")
    log("    - cable stripped, green (D+) and black (GND) exposed")
    log("    - RED wire NOT touched")
    log("    - tablet plugged DIRECTLY into a rear USB 2.0 port, no hub")
    log("")
    log(f"  Then, with the plug inserted in orientation {orientation.upper()}:")
    log("    1. unplug the tablet end")
    log("    2. hold Power 20-30 s until the screen is dark")
    log("    3. twist green+black together and HOLD")
    log("    4. plug the cable into the tablet")
    log("    5. plug the A end into the PC")
    log("    6. hold the short 5 s, then release")
    log("")
    log("  watching up to %.0f s ..." % seconds)

    before = tablet_nodes()
    log(f"  before: {classify(before)}  {before or ''}")

    left_at = None
    appeared = None
    seen_nodes: set[str] = set()
    end = time.time() + seconds
    prev_all = usb_nodes()
    while time.time() < end:
        cur = tablet_nodes()
        for n in cur:
            if n not in seen_nodes:
                seen_nodes.add(n)
                log(f"  + {n}")
        now_all = usb_nodes()
        for new in now_all - prev_all:
            if "VID_" in new.upper() and "05C6" not in new.upper():
                pass  # other traffic, ignore
        prev_all = now_all
        if left_at is None and not cur:
            left_at = time.time()
            log("  - device left the bus")
        if left_at is not None and cur and appeared is None:
            appeared = time.time()
            log("  + device returned")
        time.sleep(0.05)

    time.sleep(1.5)
    final = tablet_nodes()
    verdict = classify(final)
    rc = read_port()
    port = f"exit={rc}" if rc in (0, 1) else rc
    hello = "see log above (raw packet saved to hello_captures/ if read)"
    log("")
    log(f"  VERDICT ({orientation.upper()}) : {verdict}")
    log(f"  HELLO read              : {port}")

    rec = json.loads(OUT.read_text()) if OUT.exists() else {}
    rec.setdefault(orientation.upper(), {})
    rec[orientation.upper()]["when"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec[orientation.upper()]["verdict"] = verdict
    rec[orientation.upper()]["hello_exit"] = rc
    rec[orientation.upper()]["nodes"] = final
    OUT.write_text(json.dumps(rec, indent=2))
    log(f"  saved to {OUT}")

    if verdict == "EDL-9008":
        log("")
        log("  *** 9008 REACHED - this is the state the goal asks for. ***")
        if rc == 0:
            log("  *** and the HELLO came back ver=3 mode=0: THE GOAL IS MET ***")
            return 0
        log("  But `hello_exit=1`: the node exists and the HELLO was not obtainable")
        log("  (already spent, or WinUSB owns the node instead of a COM port).")
        log("  Switch the driver and repeat: Switch-DeviceDriver.ps1 -To COM (elevated)")
        return 1
    if verdict == "crashdump-900E":
        log("")
        log("  Still 900E: the short was not seen in this orientation.")
        log("  Flip the plug and run with the other orientation - a USB-C cable")
        log("  reaches D+ on only one side (docs/93).")
    elif verdict.startswith("wedged"):
        log("")
        log("  Wedged again: power down 20-30 s before the next attempt.")
    else:
        log("")
        log("  No device: check the short is on the right pair, and that the")
        log("  cable is not a charge-only one (a charge-only cable has no D+).")
    return 1


def summary() -> int:
    if not OUT.exists():
        log("no attempts recorded yet")
        return 1
    rec = json.loads(OUT.read_text())
    log("=" * 74)
    log("#  Short-attempt summary")
    log("=" * 74)
    for o in ("A", "B"):
        if o in rec:
            log(f"  orientation {o}: {rec[o]['verdict']:<20} hello_exit={rec[o].get('hello_exit')}")
        else:
            log(f"  orientation {o}: not tried")
    log("")
    verdicts = {o: rec[o]["verdict"] for o in ("A", "B") if o in rec}
    if "EDL-9008" in verdicts.values():
        log("  *** 9008 reached. The goal's state is obtainable by this method. ***")
    elif len(verdicts) == 2 and set(verdicts.values()) == {"crashdump-900E"}:
        log("  Both orientations give 900E: the short is not being seen.")
        log("  Most likely causes: charge-only cable (no D+), the short is on the")
        log("  wrong pair, or the firmware's own D+ driver wins (docs/79 §6).")
        log("  Next option: the test-point / battery-disconnect route (docs/88).")
    else:
        log("  Incomplete or mixed results - record both orientations before concluding.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orientation", choices=["A", "B", "a", "b"])
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if args.summary:
        return summary()
    if not args.orientation:
        log("give --orientation A or B, or --summary")
        return 2
    return run(args.orientation.upper(), args.seconds)


if __name__ == "__main__":
    sys.exit(main())
