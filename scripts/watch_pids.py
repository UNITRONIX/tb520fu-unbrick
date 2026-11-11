#!/usr/bin/env python3
"""watch_pids.py - log every VID_05C6 PID transition across a power cycle, fast.

Why this is worth doing
-----------------------
Every watcher in this project filtered for a specific PID (900E, or 9008), so a
device that enumerates as something else *in between* would be invisible.

The 15-16 s absence window during boot is the only unexplained gap in the boot
sequence. If the SoC raises an EDL endpoint there - even briefly - that is a
clean PBL-level `9008` with a pending HELLO, which is exactly the state the
Sahara upload needs and the state that has only ever been reached by a manual
bump.

Method
------
`Get-PnpDevice` costs hundreds of milliseconds per call, which is far too coarse
to catch a short window. This enumerates the device tree directly through
SetupAPI via ctypes, which costs a few milliseconds per pass, and records every
distinct transition.

Passive: it only reads the device list. It never opens a device, so it cannot
perturb what it measures.

Usage
    python watch_pids.py --seconds 120
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

# ---- SetupAPI ------------------------------------------------------------
DIGCF_PRESENT = 0x02
DIGCF_ALLCLASSES = 0x04

HDEVINFO = ctypes.c_void_p

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                          ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("ClassGuid", ctypes.c_byte * 16),
                ("DevInst", wt.DWORD),
                ("Reserved", ctypes.c_void_p)]


setupapi.SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, wt.DWORD,
                                           ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    HDEVINFO, ctypes.POINTER(SP_DEVINFO_DATA),
    wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)]

T0 = time.time()


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {msg}", flush=True)


def enumerate_05c6() -> frozenset[str]:
    """All present device instance IDs containing VID_05C6."""
    found: set[str] = set()
    hdev = setupapi.SetupDiGetClassDevsW(None, None, None,
                                        DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if hdev == wt.HANDLE(-1).value or hdev is None:
        return frozenset()
    try:
        buf = ctypes.create_unicode_buffer(1024)
        need = wt.DWORD()
        idx = 0
        while True:
            did = SP_DEVINFO_DATA()
            did.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(hdev, idx, ctypes.byref(did)):
                break
            idx += 1
            if setupapi.SetupDiGetDeviceInstanceIdW(
                    hdev, ctypes.byref(did), buf, 1024, ctypes.byref(need)):
                s = buf.value
                if "VID_05C6" in s.upper():
                    found.add(s)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return frozenset(found)


def pid_of(instance: str) -> str:
    """Instance IDs look like 'USB\\VID_05C6&PID_900E\\B6F2DE0A' - PID is inside
    the second component, joined to the VID with '&', not a separate component."""
    up = instance.upper()
    i = up.find("PID_")
    if i < 0:
        return "?"
    return up[i + 4:i + 8]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120.0)
    args = ap.parse_args()

    log("=" * 72)
    log("#  watching every VID_05C6 PID - power cycle the tablet now")
    log("=" * 72)

    prev = enumerate_05c6()
    log(f"initial: {sorted(pid_of(i) for i in prev) or ['none']}")

    events: list[tuple[float, str]] = []
    deadline = time.time() + args.seconds
    passes = 0
    while time.time() < deadline:
        cur = enumerate_05c6()
        passes += 1
        if cur != prev:
            gone, new = prev - cur, cur - prev
            parts = []
            if gone:
                parts.append("-GONE " + ",".join(sorted({pid_of(i) for i in gone})))
            if new:
                parts.append("+APPEAR " + ",".join(sorted({pid_of(i) for i in new})))
            line = "   ".join(parts)
            log(line)
            events.append((time.time() - T0, line))
            prev = cur

    log("")
    log(f"  {passes} passes in {args.seconds:.0f}s "
        f"({args.seconds / max(1, passes) * 1000:.2f} ms/pass)")
    log("=" * 72)
    log("#  sequence")
    log("=" * 72)
    if not events:
        log("  no transitions at all - the device never left the bus")
    for t, line in events:
        log(f"  {t:8.3f}  {line}")

    seen: set[str] = set()
    for _, line in events:
        for tok in line.replace("+APPEAR", " ").replace("-GONE", " ").split():
            for p in tok.split(","):
                if p:
                    seen.add(p)
    log("")
    log(f"  distinct PIDs observed: {sorted(seen) or ['none']}")
    if "9008" in seen:
        log("  *** 9008 APPEARED NATURALLY - there is a real EDL window at boot ***")
    else:
        log("  no 9008 at any point during the cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
