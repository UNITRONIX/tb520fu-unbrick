"""wait_disconnect.py - time a genuine discharge, and prove it happened.

Why this exists
---------------
Every power cycle in this project's history has been a **key-hold reset**, and a key-hold
reset leaves the RTC and the always-on domains alive. That is not an assumption, it is the
reason four separate findings are all still open:

    dload_entry_count is preserved across a key-hold reset   docs/59 s4a
    the TCSR cookie at 0x1FD9000 never clears (always-on)    docs/68 s4
    the EUD flag at 0x088E2000 never clears (always-on)      docs/74, docs/80
    no genuine off state has ever been observed here          docs/51

docs/42 lists "a discharge restores the HELLO" as **NOT tested**, and it still was, as of
this session. So the single cheapest experiment left in the whole project has never been
run.

This tool makes it measurable instead of hopeful. It watches the tablet node and reports:

  * when it left the bus (cable out),
  * how long it stayed absent,
  * whether it ever came back **without being plugged in** - which would mean the reset
    was a reset, not a power-off.

The verdict is about the DEVICE being absent from USB for long enough that the only power
it could still have is residual. 30 minutes is the threshold docs/87 recommends; shorter
gaps cannot be distinguished from an ordinary reset.

Why absence is the right signal
-------------------------------
The tablet cannot report its own power state to the host - it is off. What the host CAN
observe is that nothing enumerates. A device that is truly unpowered stays absent for the
whole window; a key-hold reset comes back in ~16 s (measured, docs/35). So a 30-minute
silence with the cable out is the strongest statement available from this side.

Usage
    python wait_disconnect.py --minutes 30
    python wait_disconnect.py --minutes 30 --expect-plug   # then prompt to plug in
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tablet as T  # noqa: E402


def log(m: str = "") -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0,
                    help="how long to require absence (docs/87 suggests 30-60)")
    ap.add_argument("--expect-plug", action="store_true",
                    help="after the wait, watch for the tablet to be plugged back in")
    ap.add_argument("--poll", type=float, default=0.5)
    args = ap.parse_args()

    need = args.minutes * 60.0
    log("=" * 74)
    log("#  discharge timer")
    log("=" * 74)
    log(f"  required absence: {args.minutes:.0f} min ({need:.0f} s)")
    log("")
    log("  Do this now:")
    log("    1. UNPLUG the USB cable")
    log("    2. hold Power 20-30 s until the screen is dark")
    log("    3. leave it unpowered - do not touch it, do not plug anything in")
    log("")

    present = T.tablet_on_bus()
    if present:
        log("  tablet is ON the bus right now - waiting for you to unplug it")
        while T.tablet_on_bus():
            time.sleep(args.poll)
        log("  device left the bus - the clock starts now")
    else:
        log("  device is already absent - the clock starts now")

    t0 = time.time()
    last_report = 0
    while True:
        away = time.time() - t0
        if T.tablet_on_bus():
            # Coming back without power being applied means the previous state was a
            # reset, not an off state - and the discharge has to start over.
            log(f"  !! DEVICE RETURNED after {away:.0f}s - that is a RESET, not an off state")
            log("     (a genuine power-off cannot re-enumerate on its own)")
            log("     unplug it and start again")
            return 1
        if away >= need:
            break
        if away - last_report >= 60:
            last_report = away
            log(f"  absent {away / 60:.0f} min of {args.minutes:.0f} min")
        time.sleep(args.poll)

    log("")
    log(f"  *** ABSENT for {need / 60:.0f} min - the discharge condition is met ***")
    log("  Residual power in the RTC / always-on domain has had time to bleed off.")
    log("  The next boot is the first genuinely cold one this unit may have had.")
    log("")
    log("  Now:")
    log("    1. plug the cable into the SAME socket (docs/105: it is bound to qcwdfser)")
    log("    2. do NOT hold any key")
    log("    3. run: python tablet.py catch --seconds 180")

    if args.expect_plug:
        log("")
        log("  watching for the tablet to come back...")
        t1 = time.time()
        while time.time() - t1 < 300:
            pids = T.pids_present()
            if pids:
                log(f"  + came back as {sorted(set(pids.values()))} "
                    f"after {time.time() - t1:.1f}s")
                com = T.com_port()
                log(f"  COM port: {com or 'none'}")
                if com:
                    log("  reading the HELLO now")
                    return T.grab_any_hello(10.0)
                log("  no COM port - check driver_check.py for this socket (docs/105)")
                return 1
            time.sleep(0.05)
        log("  nothing appeared within 300 s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
