#!/usr/bin/env python3
"""edl_coach.py - guided forced-EDL attempt, with release timing and recording.

Read this before running
------------------------
The premise most people start with is wrong, so it is corrected here first.

The forced-EDL check reads the USB D+ line during **bootloader initialisation**,
which happens *before* the device appears on the USB bus. Measured on this tablet,
the device is absent from USB for ~15 s during that phase. Consequences:

  * you cannot use USB presence as the signal to "press now" - there is nothing
    to observe at the moment the check runs;
  * the short must already be applied when firmware looks, so it has to be
    engaged **before power is applied**;
  * the check window itself is short (~50 ms, per docs/18-escalation-surfaces.md),
    which is why a "hold and wait" strategy is the only workable one.

So this tool does not tell you when to press. It does three things that are
actually useful:

  1. identify   - work out what the cable's button does, by watching USB while
                  you press it on a running device
  2. attempt    - talk you through the sequence in order, and tell you when to
                  RELEASE (the one genuinely time-sensitive action)
  3. watch      - passive high-rate USB monitoring, for use in parallel

And it records every transition with a timestamp, so a failed attempt produces
evidence instead of a feeling.

Read-only. It never writes to the device, never uploads a programmer, and never
sends Sahara commands.

Usage
    python edl_coach.py identify
    python edl_coach.py attempt
    python edl_coach.py watch --seconds 120

Requires: pyusb (already used elsewhere in this repo)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import usb.core
except ImportError:
    print("pyusb is required: python -m pip install pyusb")
    raise SystemExit(2)

OUT = Path(__file__).resolve().parent / "edl_coach"

#: VID:PID values that matter here.
KNOWN = {
    (0x05C6, 0x9008): "9008  EDL (Sahara, programmer-loadable)",
    (0x05C6, 0x900E): "900E  crashdump",
    (0x05C6, 0x9006): "9006  diag/download",
    (0x05C6, 0x900E): "900E  crashdump",
    (0x17EF, 0x0000): "Lenovo",
}

#: Anything else on the bus that might appear mid-boot.
INTERESTING_VIDS = {0x05C6, 0x17EF, 0x18D1, 0x2A70, 0x2717}

T0 = time.time()


def log(msg: str = "") -> None:
    elapsed = time.time() - T0
    stamp = f"[{elapsed:8.3f}]"
    print(f"{stamp} {msg}", flush=True)


def banner(title: str) -> None:
    print()
    print("=" * 74)
    print(f"  {title}")
    print("=" * 74)


def now_iso() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ---------------------------------------------------------------------------
# USB state snapshot
# ---------------------------------------------------------------------------
def qcom_state() -> tuple[str, str]:
    """Return (state_label, detail) for the Qualcomm devices currently present."""
    found = []
    try:
        for dev in usb.core.find(find_all=True):
            vid = getattr(dev, "idVendor", None)
            pid = getattr(dev, "idProduct", None)
            if vid is None or pid is None:
                continue
            if (vid, pid) in KNOWN:
                found.append((vid, pid, KNOWN[(vid, pid)]))
            elif vid in INTERESTING_VIDS:
                found.append((vid, pid, f"{vid:04x}:{pid:04x} (interesting vid)"))
    except Exception as err:  # noqa: BLE001
        return "error", f"usb scan failed: {type(err).__name__}"

    if not found:
        return "absent", ""

    # prioritise the two states that matter
    for vid, pid, label in found:
        if (vid, pid) == (0x05C6, 0x9008):
            return "9008", label
    for vid, pid, label in found:
        if (vid, pid) == (0x05C6, 0x900E):
            return "900E", label
    vid, pid, label = found[0]
    return f"{vid:04x}:{pid:04x}", label


class Recorder:
    """Records state transitions with wall-clock and relative timestamps."""

    def __init__(self, mode: str) -> None:
        OUT.mkdir(exist_ok=True)
        self.mode = mode
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = OUT / f"{self.stamp}_{mode}.jsonl"
        self.file = self.path.open("w", encoding="utf-8")
        self.last_state = None
        self.transitions: list[dict] = []

    def feed(self, state: str, detail: str) -> bool:
        """Record a transition if the state changed. Returns True if it changed."""
        if state == self.last_state:
            return False
        entry = {
            "wall": now_iso(),
            "t_rel": round(time.time() - T0, 4),
            "state": state,
            "detail": detail,
        }
        self.file.write(json.dumps(entry) + "\n")
        self.file.flush()
        self.last_state = state
        self.transitions.append(entry)
        return True

    def close(self) -> None:
        self.file.close()


# ---------------------------------------------------------------------------
# Mode: identify what the button does
# ---------------------------------------------------------------------------
def mode_identify(args) -> int:
    banner("IDENTIFY - what does the cable's button actually do?")
    print("""
This works on a device that is ALREADY enumerated and stable.

It watches USB continuously and prints anything that changes while you press and
hold the button. Three outcomes are possible and each means something different:

  * the device disappears while held, returns on release
        -> the button shorts the data lines / cuts the link. That is the EDL-cable
           behaviour, and it means the button must be held from before power-on.
  * nothing changes at all
        -> either the button is not wired to anything this device responds to while
           running, or it only affects the boot path (common, and not a fault).
  * a new device appears
        -> the button triggers a mode change. Note the VID:PID it produces.

Press the button only when told. Release after the hold period is reported.
""".rstrip())

    state, detail = qcom_state()
    log(f"current state: {state}  {detail}")
    if state == "absent":
        log("!! no device on the bus. Plug the tablet in first, then re-run.")
        return 1

    rec = Recorder("identify")
    rec.feed(state, detail)

    print()
    input("  >>> Press ENTER when you are ready, then HOLD the button.\n  > ")

    log("now: HOLD the button. Watching for 8 s ...")
    hold_start = time.time()
    baseline = state
    seen_during = []
    while time.time() - hold_start < 8.0:
        s, d = qcom_state()
        if rec.feed(s, d):
            log(f"  CHANGE -> {s}  {d}")
            seen_during.append(s)
        time.sleep(0.02)

    log("now: RELEASE the button. Watching for 12 s ...")
    rel_start = time.time()
    while time.time() - rel_start < 12.0:
        s, d = qcom_state()
        if rec.feed(s, d):
            log(f"  CHANGE -> {s}  {d}")
        time.sleep(0.02)

    rec.close()
    final, fdetail = qcom_state()

    banner("RESULT")
    log(f"baseline        : {baseline}")
    log(f"states while held: {seen_during or '(no change)'}")
    log(f"final state     : {final}  {fdetail}")
    log(f"recorded to     : {rec.path}")
    print()
    if baseline not in seen_during and final == baseline and not seen_during:
        print("  Verdict: the button had NO observable effect on a running device.")
        print("  That is the normal case for an EDL cable - its short only matters")
        print("  during boot. Proceed with 'attempt'.")
    elif "absent" in seen_during or any(s not in (baseline,) for s in seen_during):
        print("  Verdict: the button DOES change USB state while running.")
        print("  That confirms it shorts the link. It must therefore be held from")
        print("  before power-on: see 'attempt'.")
    else:
        print("  Verdict: inconclusive; check the cable seating and retry.")
    return 0


# ---------------------------------------------------------------------------
# Mode: guided attempt
# ---------------------------------------------------------------------------
def mode_attempt(args) -> int:
    banner("ATTEMPT - guided forced-EDL sequence")
    print("""
Why the order below is what it is
---------------------------------
The firmware samples the D+ line during bootloader init, before USB exists. The
sample window is ~50 ms and happens once. So:

  the short cannot be timed into the window - it must BE there when the code runs.

That is why the button is engaged before power, and released after the device
appears. There is exactly one time-sensitive action in this procedure, and it is
the release.

  STEP 1   unplug everything
  STEP 2   press and HOLD the button - do not let go
  STEP 3   connect USB (this applies power)
  STEP 4   watch; the tool tells you when to release
  STEP 5   if 9008 appears -> forced EDL worked
           if 900E appears -> it did not; the short was not seen
           if nothing         -> no enumeration at all

Do not release early to "check". Releasing during the sample window is the single
most common way this fails.
""".rstrip())

    rec = Recorder("attempt")
    print()
    input("  STEP 1-2: unplug the cable, then press and HOLD the button.\n"
          "            Press ENTER while still holding it.\n  > ")
    log("button assumed HELD.")

    print()
    print("  STEP 3: connect the USB cable NOW.")
    print("          You have a short grace period before watching starts;")
    print("          keep the button held the whole time.")
    print()
    for remaining in (3, 2, 1):
        print(f"          connecting window: {remaining} ...", end="\r", flush=True)
        time.sleep(1.0)
    print(" " * 40, end="\r")

    log("watching for the device. Keep holding until told to release.")

    appeared_at = None
    state_seen = None
    deadline = time.time() + args.window
    released = False
    last_print = 0.0

    while time.time() < deadline:
        s, d = qcom_state()
        if rec.feed(s, d):
            log(f"  CHANGE -> {s}  {d}")

        if appeared_at is None and s != "absent":
            appeared_at = time.time()
            state_seen = s
            if s == "9008":
                print()
                print("  " + "!" * 66)
                print("  >>>  RELEASE THE BUTTON NOW  -  9008 appeared  <<<")
                print("  " + "!" * 66)
                released = True
            else:
                print()
                print(f"  device appeared as {s}. Holding 1.5 s more, then release.")

        # for a non-9008 appearance, give a short hold then instruct release
        if appeared_at is not None and not released and time.time() - appeared_at > 1.5:
            print("  >>>  RELEASE THE BUTTON NOW  <<<")
            released = True

        # heartbeat so a silent window is visibly alive
        if time.time() - last_print > 2.0:
            log(f"  ... still watching ({s}), {deadline - time.time():.0f}s left")
            last_print = time.time()

        time.sleep(0.02)

    rec.close()

    banner("RESULT")
    if appeared_at is None:
        log("  The device never appeared on USB during the whole window.")
        print()
        print("  Possible reasons, in order of likelihood:")
        print("    - the short was not seen, so boot did not reach the USB stage;")
        print("    - the cable is charge-only (no data lines connected);")
        print("    - the tablet is fully powered down and the button is also the")
        print("      power button, so nothing booted;")
        print("    - the previous session left it wedged.")
        print(f"\n  Record: {rec.path}")
        return 1

    log(f"  first appearance : {state_seen}")
    log(f"  time to appear   : {appeared_at - T0:.3f}s after pressing ENTER")
    log(f"  record           : {rec.path}")
    print()
    if state_seen == "9008":
        print("  FORCED EDL SUCCEEDED. The device is in 9008 and will accept a")
        print("  Sahara programmer. Do not unplug it.")
        print()
        print("  Next, in a separate terminal:")
        print("    python sahara_exec_9008.py      (verify command mode on the PBL)")
        print("    python crash_region_probe.py    (if you need the crash dump)")
    elif state_seen == "900E":
        print("  The device came up in 900E (crashdump), not 9008.")
        print("  That means it booted far enough for the crash handler but the short")
        print("  was not interpreted as a forced-EDL request. Try again with the")
        print("  button held for longer before connecting, and release only on")
        print("  instruction.")
    else:
        print(f"  The device appeared as {state_seen}. Note it and check whether it")
        print("  exposes a new interface - that would be a mode worth investigating.")
    return 0


# ---------------------------------------------------------------------------
# Mode: passive watch
# ---------------------------------------------------------------------------
def mode_watch(args) -> int:
    banner(f"WATCH - passive USB monitoring for {args.seconds:.0f}s")
    rec = Recorder("watch")
    s, d = qcom_state()
    rec.feed(s, d)
    log(f"initial: {s}  {d}")

    end = time.time() + args.seconds
    while time.time() < end:
        st, de = qcom_state()
        if rec.feed(st, de):
            log(f"  CHANGE -> {st}  {de}")
        time.sleep(0.02)

    rec.close()
    banner("TRANSITIONS")
    for t in rec.transitions:
        log(f"  +{t['t_rel']:8.3f}s  {t['state']:<10} {t['detail']}")
    log(f"record: {rec.path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("identify", help="work out what the button does")
    p1.set_defaults(func=mode_identify)

    p2 = sub.add_parser("attempt", help="guided forced-EDL attempt")
    p2.add_argument("--window", type=float, default=45.0,
                    help="how long to watch for the device (s)")
    p2.set_defaults(func=mode_attempt)

    p3 = sub.add_parser("watch", help="passive monitoring")
    p3.add_argument("--seconds", type=float, default=120.0)
    p3.set_defaults(func=mode_watch)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
