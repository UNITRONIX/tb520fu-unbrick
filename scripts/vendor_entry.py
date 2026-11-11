#!/usr/bin/env python3
"""vendor_entry.py - run the manufacturer's entry procedure with verification at each step.

The ROM package's own instruction card (pics/Volume up.JPG) says:

    In power off status, keep Volume up key pressing and then connect device to
    computer.
    If no COM port device list below, please try again.

Three words carry all the difficulty - "in power off status" - because
docs/07 sE2 recorded that this tablet "cannot be powered off: power always
returns to logo, then crashdump". Every cycle in this repository has been a
key-hold reset, which leaves the RTC and always-on domains alive and is NOT the
same thing.

So a procedure that just says "power off and hold the key" has been tried and
failed, without anyone knowing whether the first precondition was ever met. This
script makes every step observable:

    step 1  wait for the device to LEAVE the bus and STAY away  (a real off state)
    step 2  confirm it is still away when the key goes down
    step 3  watch for it to come back, and report what came back

If step 1 never succeeds, the run is reported as "could not reach an off state"
- which is a different finding from "the key did not work", and the two have been
conflated in this project before.

Read-only: it enumerates USB and, if a port appears, reads one packet to report
what it is. It never writes to the device.

Usage
    python vendor_entry.py --seconds 180
    python vendor_entry.py --key down       # try Volume Down instead of Up
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tablet  # noqa: E402

T0 = time.time()
DIGCF_PRESENT = 0x02
DIGCF_ALLCLASSES = 0x04
HDEVINFO = ctypes.c_void_p

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                          ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
setupapi.SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, wt.DWORD, ctypes.c_void_p]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    HDEVINFO, ctypes.c_void_p, wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)]


class _DID(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", ctypes.c_byte * 16),
                ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def usb_snapshot() -> frozenset[str]:
    found: set[str] = set()
    h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                     DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not h:
        return frozenset()
    try:
        buf = ctypes.create_unicode_buffer(1024)
        need = wt.DWORD()
        i = 0
        while True:
            d = _DID()
            d.cbSize = ctypes.sizeof(_DID)
            if not setupapi.SetupDiEnumDeviceInfo(h, i, ctypes.byref(d)):
                break
            i += 1
            if setupapi.SetupDiGetDeviceInstanceIdW(
                    h, ctypes.byref(d), buf, 1024, ctypes.byref(need)):
                s = buf.value
                if "VID_" in s.upper():
                    found.add(s)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return frozenset(found)


def tablet_present() -> bool:
    return any("VID_05C6" in x.upper() for x in usb_snapshot())


def read_packet_if_any() -> str:
    """If a Qualcomm COM port exists, report what the first packet is."""
    cp = tablet.com_port()
    if cp is None:
        return "no Qualcomm COM port"
    link = None
    try:
        link = tablet.Link(cp)
        data = link.raw(8, 3.0)
        if not data:
            return f"{cp} open, no bytes pending"
        cmd, ln = struct.unpack_from("<II", data, 0)
        name = tablet.NAMES.get(cmd, hex(cmd))
        if cmd == tablet.CMD_HELLO_REQ and ln >= 0x30:
            ver = struct.unpack_from("<I", data, 8)[0]
            mode = struct.unpack_from("<I", data, 20)[0]
            return f"{cp}: *** HELLO ver={ver} mode={mode} ***"
        return f"{cp}: {name} len={ln}"
    except Exception as err:  # noqa: BLE001
        return f"{cp} could not be opened ({type(err).__name__})"
    finally:
        if link:
            link.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--key", choices=["up", "down", "both"], default="up")
    ap.add_argument("--off-threshold", type=float, default=25.0,
                    help="absence longer than this counts as a genuine off state")
    args = ap.parse_args()

    key_name = {"up": "Volume UP", "down": "Volume DOWN",
                "both": "Volume UP + Volume DOWN"}[args.key]

    log("=" * 72)
    log("#  Vendor entry procedure, with every step verified")
    log("=" * 72)
    log("")
    log("  What you will do:")
    log("    1. UNPLUG the USB cable")
    log("    2. hold Power until the screen goes dark and stays dark")
    log(f"    3. hold {key_name}")
    log("    4. still holding it, plug the cable back in")
    log("    5. keep holding ~10 s")
    log("")
    log(f"  Key under test: {key_name}")
    log("  (docs/47: Volume Up is PM8550 gpio6 and needs a driver; Volume Down")
    log("   and Power are PMIC PON inputs and need none)")
    log("")

    deadline = time.time() + args.seconds

    # ---- step 1: wait for a genuine absence ----------------------------
    log("STEP 1 - waiting for the device to leave the bus and STAY away")
    if tablet_present():
        log(f"  device present now; unplug and power it down (budget {args.seconds:.0f}s)")

    absent_since = None
    off_confirmed = False
    while time.time() < deadline:
        here = tablet_present()
        now = time.time()
        if here:
            if absent_since is not None:
                away = now - absent_since
                log(f"  + came BACK after {away:.1f}s"
                    f"  -> {'RESET (too short to be off)' if away < args.off_threshold else 'returned'}")
                absent_since = None
                off_confirmed = False
            time.sleep(0.08)
            continue
        if absent_since is None:
            absent_since = now
            log("  - absent, timing the gap...")
        away = now - absent_since
        if not off_confirmed and away >= args.off_threshold:
            off_confirmed = True
            log(f"  *** ABSENT {away:.0f}s -> genuine OFF state reached ***")
            log(f"  STEP 2 - now hold {key_name} and plug the cable in")
        time.sleep(0.08)

        # ---- step 3: did it come back while we held? ------------------
        if off_confirmed and here:
            break

    if not off_confirmed:
        log("")
        log("RESULT: could not reach a genuine OFF state in the window.")
        log("  That is NOT 'the key did not work' - the procedure's first")
        log("  precondition was never met. docs/07 sE2 recorded this device always")
        log("  returns to logo then crashdump; this run confirms it under timing.")
        tablet.record("vendor_entry", ok=False, reason="no-off-state", key=args.key)
        return 1

    # ---- step 3: watch for the return ---------------------------------
    log("")
    log("STEP 3 - watching for the device to come back")
    result_pid = None
    seen_new: set[str] = set()
    before = usb_snapshot()
    while time.time() < deadline:
        now_snap = usb_snapshot()
        for new in now_snap - before:
            if "VID_" in new.upper():
                seen_new.add(new)
                log(f"  + APPEAR {new}")
        before = now_snap
        p = tablet.pids_present()
        if p:
            pids = list(p.values())
            log(f"  device node present: {pids}")
            result_pid = pids[0]
            break
        time.sleep(0.08)

    if result_pid is None:
        log("")
        log("RESULT: nothing came back in the window.")
        log("  With a key held and the cable re-inserted, silence means the entry")
        log("  did not trigger - which for this key is a real negative result.")
        tablet.record("vendor_entry", ok=False, reason="never-returned", key=args.key)
        return 1

    log("")
    log(f"RESULT: device returned as PID_{result_pid}")
    detail = read_packet_if_any()
    log(f"  port: {detail}")
    if result_pid == "9008":
        log("  *** 9008 - this is the EDL state the goal asks for ***")
    elif "HELLO" in detail:
        log("  *** a HELLO is readable - route A (bump) is now possible ***")
    tablet.record("vendor_entry", ok=True, pid=result_pid, detail=detail, key=args.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
