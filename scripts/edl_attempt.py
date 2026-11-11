"""edl_attempt.py - run the D+ short attempt and capture everything it produces.

Why this exists
---------------
The attempt made at 20:27 produced a real signal that was almost invisible: the device
enumerated at **FullSpeed** with a null descriptor. A wedge that happens *before* USB
enumeration cannot report a speed, because the hub has no idea what the device is until the
descriptor exchange. So the device got further than the previous wedges did - the PHY trained
and answered - and then handed back zeros.

That distinction was only visible because two separate measurements (the port's Speed byte
and the descriptor length) were read together. A run that reports "no COM port, failed"
throws that away.

What it records, per attempt
----------------------------
  * a timestamped marker file, so a later dump can be tied to this attempt,
  * the port's full state before and after: speed, address, pipes, descriptor length, status,
  * every USB arrival/departure during the window, unfiltered,
  * whether a COM port ever appeared,
  * the host-side retry accounting afterwards.

The marker matters more than it looks. The only way to know whether the D+ short latched is
to read `Boot Config @ 0x221C8600` out of the boot log (scripts/fedl_latch.py), and a boot log
found in a capture needs to be attributable to a specific physical attempt. Without a marker
file, "which boot was that?" is unanswerable a day later.

Usage
    python edl_attempt.py --label "short-A-2019" --seconds 90
    python edl_attempt.py --summary
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reset_port as R  # noqa: E402
import tablet as T  # noqa: E402
import watch_unknown as W  # noqa: E402

OUT = HERE / "edl_attempts.jsonl"

SPEEDS = {0: "unknown", 1: "LowSpeed(1.5M)", 2: "FullSpeed(12M)", 3: "HighSpeed(480M)",
          4: "SuperSpeed(5G)"}


def tablet_port() -> tuple[str | None, int | None, str]:
    for path in R.hub_interface_paths():
        h, _ = R.open_hub(path)
        if not h:
            continue
        try:
            for port in range(1, 9):
                st = R.port_state(h, port)
                if st is None:
                    break
                # The tablet is the port whose vid/pid came back zero but which the hub
                # considers enumerated - a real device answers with a real descriptor.
                if st["status"] == 2 and st["vid"] == 0 and st["pid"] == 0:
                    return path, port, "null-descriptor node"
        finally:
            R.CloseHandleSafe(h)
    return None, None, "not found"


def port_detail(path: str, port: int) -> dict:
    """Full fixed part of the port's response, with named fields."""
    h, _ = R.open_hub(path)
    if not h:
        return {}
    try:
        size = 4096
        buf = ctypes.create_string_buffer(size)
        ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = port
        ret = wt.DWORD()
        ok = R.kernel32.DeviceIoControl(
            h, R.IOCTL_GET_NODE_CONNECTION_INFORMATION_EX,
            buf, size, buf, size, ctypes.byref(ret), None)
        if not ok or ret.value < 35:
            return {}
        raw = buf.raw[:35]
        speed_num = raw[23]
        return {
            "status": int.from_bytes(raw[31:35], "little"),
            "status_name": R.describe(int.from_bytes(raw[31:35], "little")),
            "speed": SPEEDS.get(speed_num, speed_num),
            "speed_num": speed_num,
            "address": int.from_bytes(raw[25:27], "little"),
            "pipes": int.from_bytes(raw[27:31], "little"),
            "descriptor_len": raw[4],
            "vid": int.from_bytes(raw[12:14], "little"),
            "pid": int.from_bytes(raw[14:16], "little"),
        }
    finally:
        R.CloseHandleSafe(h)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None, help="name this attempt, e.g. short-A")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    if args.summary:
        if not OUT.is_file():
            print("no attempts recorded")
            return 1
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            print(f"{r['when']}  {r.get('label',''):18s} "
                  f"before={r.get('before',{}).get('status_name','?'):20s} "
                  f"after={r.get('after',{}).get('status_name','?'):20s} "
                  f"speed={r.get('after',{}).get('speed','?')} "
                  f"com={r.get('com') or 'none'}")
        return 0

    label = args.label or time.strftime("attempt-%H%M%S")
    marker = HERE / "edl_markers" / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.txt"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(
        f"label: {label}\nwhen: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"purpose: D+ short attempt; find the matching boot log with fedl_latch.py\n",
        encoding="utf-8")

    print("=" * 74)
    print(f"#  EDL attempt: {label}")
    print("=" * 74)
    print(f"  marker written: {marker.name}")
    print("")

    path, port, why = tablet_port()
    before = {}
    if path:
        before = port_detail(path, port)
        print(f"  port {port} on {path.split('#')[1][:28]}...  ({why})")
        print(f"    before: {before.get('status_name')}  speed={before.get('speed')} "
              f"addr={before.get('address')} pipes={before.get('pipes')} "
              f"dlen={before.get('descriptor_len')}")
    else:
        print(f"  {why}")

    print("")
    print("  Procedure for the D+ short (docs/109 - the check is at ~1036 ms):")
    print("    1. tablet OFF, cable already plugged into the PC")
    print("    2. apply the short on D+/GND")
    print("    3. power on with the short held")
    print("    4. keep holding through at least 1.5 s of boot")
    print("")
    print(f"  watching {args.seconds:.0f}s, every USB node, no filter ...")

    ns_before = W.snapshot(None, True)
    events: list[str] = []
    end = time.time() + args.seconds
    prev = ns_before
    com_seen = None
    while time.time() < end:
        cur = W.snapshot(None, True)
        if cur != prev:
            for k in cur.keys() - prev.keys():
                events.append(f"+ {k} at {cur[k]}")
                print(f"  + ARRIVED {k}  {cur[k]}")
            for k in prev.keys() - cur.keys():
                events.append(f"- {k}")
                print(f"  - LEFT    {k}")
            for k in cur.keys() & prev.keys():
                if cur[k] != prev[k]:
                    events.append(f"~ {k} {cur[k]}")
                    print(f"  ~ RE-ARRIVED {k}  {cur[k]}")
            prev = cur
        if com_seen is None:
            com_seen = T.com_port()
        time.sleep(0.08)

    after = {}
    path2, port2, _ = tablet_port()
    if path2:
        after = port_detail(path2, port2)

    print("")
    print(f"  after : {after.get('status_name','?')}  speed={after.get('speed','?')} "
          f"addr={after.get('address','?')} pipes={after.get('pipes','?')} "
          f"dlen={after.get('descriptor_len','?')}")
    print(f"  COM   : {com_seen or 'none'}")
    print(f"  events: {len(events)}")

    # Verdict, in the terms that decide the next step.
    print("")
    if com_seen:
        print("  A COM PORT APPEARED - read the HELLO now:")
        print("    python tablet.py edl-hello --timeout 15")
    elif after.get("descriptor_len") == 18:
        print("  A REAL DESCRIPTOR CAME BACK but no COM port - the socket is bound to")
        print("  libwdi WinUSB (docs/105). Switch it, then repeat:")
        print("    powershell -ExecutionPolicy Bypass -File Switch-DeviceDriver.ps1 -To COM")
    elif after.get("status_name") == "DeviceEnumerated" and after.get("speed_num", 0) >= 2:
        # The hub trains the PHY to a speed BEFORE the descriptor exchange, so a
        # non-zero speed proves the device's USB PHY is alive and driving the line.
        # It says nothing about the descriptor, which came back as zeros.
        print(f"  The hub reports {after['speed']} and DeviceEnumerated, but the")
        print("  descriptor is NULL (dlen=0, vid/pid 0). Read together, that means:")
        print("    - the device's PHY trained and answered the hub  -> the USB path works")
        print("    - the descriptor request returned zeros          -> DEVICE_DESCRIPTOR_FAILURE")
        print("  This is the same wedge as before, not a new state. To learn whether the")
        print("  short latched anything, read the boot log from a fresh capture:")
        print("    python fedl_latch.py --dump <new capture>")
    elif after.get("status_name") == "DeviceEnumerated":
        print("  Enumerated at unknown speed with a null descriptor - the port responded")
        print("  but reported no usable speed. Re-run to sample it again.")
    else:
        print("  Device absent or not enumerated. Check the short is on the right pair")
        print("  and that the cable carries data (a charge-only cable has no D+).")

    row = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "marker": marker.name,
        "before": before,
        "after": after,
        "events": events[:40],
        "com": com_seen,
    }
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(f"\n  recorded in {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
