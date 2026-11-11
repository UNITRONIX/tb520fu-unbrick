"""driver_check.py - will the tablet's COM port actually appear where it is plugged in?

Why this exists
---------------
The driver binding on Windows is per *instance id*, and a USB instance id encodes the
hub and port. So "does tablet.py find a COM port?" depends on WHICH SOCKET the cable is
in - not on the tablet, not on the build. Measured on this machine:

    VID_05C6&PID_9008\\9&1ff60ac4&0&4   -> Ports / qcwdfser     COM9   usable
    VID_05C6&PID_9008\\8&1b878445&0&2   -> USBDevice / libwdi  (none) NOT usable
    VID_05C6&PID_9008\\8&384b90af&0&4   -> USBDevice / libwdi  (none) NOT usable
    VID_05C6&PID_900E\\b6f2de0a         -> Ports / qcwdfser     COM10  usable

Three of the tablet's identities have already been bound, and two of them to libwdi's
WinUSB package - which exposes no serial port at all. A physical attempt made on one of
those sockets reaches EDL and then cannot read a byte, because there is nothing to open.
That looks exactly like "the HELLO was spent", which is the wrong conclusion and costs
another power cycle.

This tool answers the question BEFORE the cable goes in: for every known tablet
instance, which driver is bound, and what to do about it.

Usage
    python driver_check.py
    python driver_check.py --port 9&1ff60ac4&0&4
"""
from __future__ import annotations

import argparse
import sys
import winreg

BASE = r"SYSTEM\CurrentControlSet\Enum\USB"
TABLET_VIDS = ("VID_05C6&PID_9008", "VID_05C6&PID_900E", "VID_0000&PID_0002")

# Class GUIDs, which is what the enum record actually stores in `Driver`. Compared
# UPPERCASE: the registry writes `{4d36e978-e325-11ce-bfc1-08002be10318}\0002` and a
# lowercase constant silently fails to match, which made every port - including the two
# that really do expose COM9/COM10 - report as unusable. A check that always says NO is
# worse than no check.
CLASS_PORTS = "{4D36E978-E325-11CE-BFC1-08002BE10318}"
CLASS_USBDEVICE = "{88BAE032-5A81-49F0-BC3D-A4FF138216D6}"


def read_key(path: str) -> dict[str, object]:
    vals: dict[str, object] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                vals[n] = v
    except OSError:
        pass
    return vals


def subkeys(path: str) -> list[str]:
    out: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def classify(driver_value: object) -> tuple[str, bool]:
    """(human description, does it expose a serial port?)"""
    up = str(driver_value or "").upper()
    if CLASS_PORTS in up:
        return "Ports / qcwdfser", True
    if CLASS_USBDEVICE in up:
        return "USBDevice / libwdi WinUSB", False
    if not up:
        return "(no driver)", False
    return str(driver_value), False


def rows() -> list[dict]:
    out: list[dict] = []
    for vid in TABLET_VIDS:
        for inst in subkeys(f"{BASE}\\{vid}"):
            path = f"{BASE}\\{vid}\\{inst}"
            v = read_key(path)
            dp = read_key(f"{path}\\Device Parameters")
            desc, serial_ok = classify(v.get("Driver"))
            out.append({
                "instance": f"{vid}\\{inst}",
                "location": v.get("LocationInformation"),
                "driver": desc,
                "serial": serial_ok,
                "com": dp.get("PortName"),
                "retry": dp.get("EnumerationRetryCount"),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None,
                    help="only report the instance whose id ends with this suffix")
    args = ap.parse_args()

    rs = rows()
    if args.port:
        want = args.port.upper()
        rs = [r for r in rs if r["instance"].upper().endswith(want)]

    if not rs:
        print("no recorded tablet instance matches")
        return 1

    print(f"{'instance':38s} {'location':24s} {'driver':26s} {'COM':6s} serial?")
    print("-" * 110)
    usable = 0
    for r in rs:
        ok = "YES" if r["serial"] else "NO"
        if r["serial"]:
            usable += 1
        print(f"{r['instance']:38s} {str(r['location'] or ''):24s} "
              f"{r['driver']:26s} {str(r['com'] or ''):6s} {ok}")

    print()
    print(f"{usable} of {len(rs)} instance(s) can expose a COM port.")
    if usable == 0:
        print("  NONE usable: every known tablet socket is bound to libwdi WinUSB.")
        print("  A plug-in here reaches EDL and cannot be read. Fix first:")
        print("    powershell -ExecutionPolicy Bypass -File Switch-DeviceDriver.ps1 -To COM")
        return 1
    print("  Plug the cable into a socket whose row says YES - the binding is per")
    print("  port, so moving the cable can silently trade a working port for a dead one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
