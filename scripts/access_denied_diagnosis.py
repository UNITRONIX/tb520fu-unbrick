#!/usr/bin/env python3
"""access_denied_diagnosis.py - why does opening the node return Access denied?

The measurement
---------------
timing_window.py sampled the node for 80 s and got:

    present, not openable (errno 13, Access denied)   490 / 491 samples
    absent                                              0 samples

Two facts follow, and both matter:

  1. the node never left the bus for 80 s, so the tablet is **not** boot-looping any
     more - it is sitting in a steady state;
  2. opening it fails at the host, before any USB transfer, with EACCES.

EACCES on a bulk device has three common causes on Windows:
  a) another process holds the interface;
  b) the bound driver does not permit the open (e.g. a COM-port driver rather than
     WinUSB);
  c) the PnP node is in a state where libusb cannot acquire it.

This distinguishes them using information the OS will give up without administrator
rights: the bound service, the problem code, and whether a serial port now exists
that did not before (which would mean the Qualcomm COM driver took the device - the
mutually-exclusive "world B" from docs/07-dead-ends.md).

Read-only. It does not open the device.

Usage
    python access_denied_diagnosis.py
"""
from __future__ import annotations

import subprocess
import sys


def ps(cmd: str) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as err:  # noqa: BLE001
        return f"<powershell failed: {type(err).__name__}>"


def main() -> int:
    print("=" * 74)
    print("#  why is the node not openable?")
    print("=" * 74)

    print("\n#  Qualcomm nodes present")
    out = ps(
        "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_05C6' } | "
        "Select-Object Status,Class,FriendlyName,InstanceId | Format-List")
    print(out.strip() or "  (none)")

    print("\n#  bound driver service")
    out = ps(
        "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_05C6' } | "
        "ForEach-Object { $id=$_.InstanceId; "
        "$s=(Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_Service' "
        "-ErrorAction SilentlyContinue).Data; "
        "$p=(Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_ProblemCode' "
        "-ErrorAction SilentlyContinue).Data; "
        "Write-Output \"$id  service=$s  problem=$p\" }")
    print(out.strip() or "  (none)")

    print("\n#  serial ports (world B would show a Qualcomm COM port)")
    out = ps(
        "Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue | "
        "Select-Object DeviceID,Name,Description | Format-Table -AutoSize")
    print(out.strip() or "  (no serial ports)")

    print("\n#  processes holding the device (best effort, no elevation)")
    out = ps(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'edl|sahara|crash|probe|fingerprint|changing|hygiene' } | "
        "Select-Object ProcessId,CreationDate,CommandLine | Format-List")
    print(out.strip() or "  (no matching EDL processes)")

    print("\n" + "=" * 74)
    print("#  HOW TO READ THIS")
    print("=" * 74)
    print("  service=WinUSB   -> the pyusb world; EACCES means another holder or a")
    print("                      node the OS considers not ready")
    print("  service=qcser*   -> a COM driver took the device. pyusb cannot use it at")
    print("                      all; either rebind WinUSB or switch to fh_loader, and")
    print("                      do not mix the two in one session")
    print("  a new COM port   -> same conclusion as qcser: the driver world changed")
    print()
    print("  If a python process is listed, that is the simplest explanation and the")
    print("  one docs/07-dead-ends.md section F1 records: an orphan holds the handle")
    print("  and every later open reports Permission denied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
