"""watch_unknown.py - is the tablet's USB node static, or does it keep re-arriving?

Why this exists
---------------
The tablet shows up as `USB\\VID_0000&PID_0002 ... DEVICE_DESCRIPTOR_FAILURE` and that was
dismissed for hours as simply "the wedged state". The dismissal hides a distinction that
matters:

  * a node that arrived ONCE and sits in the failed state = a device that stopped talking;
  * a node that keeps RE-ARRIVING = a device that reaches USB address assignment and then
    fails the descriptor request. Still broken, but alive and retrying.

Those two call for different next steps, so this tool separates them.

Which signal to use
-------------------
DEVPKEY_Device_Address is the obvious one and it is NOT available here: reading it on a
node in CM_PROB_FAILED_POST_START returns ERROR_NOT_FOUND (1168). The instance-id suffix
(`...&0&4`) is the hub PORT, not the USB address, and it is stable across re-plugs.

What does work is DEVPKEY_Device_LastArrivalDate, a FILETIME refreshed on every new
arrival. So "static" means that timestamp never moves for the whole window.

Bugs this file already survived, both worth remembering:
  1. Without `argtypes`, a HDEVINFO pointer truncates to 32 bits and enumeration silently
     returns nothing - the first version printed a confident "the node is static" from
     zero data.
  2. A SP_DEVINFO_DATA is only valid against the HDEVINFO that produced it, so properties
     must be read inside the same enumeration that found the node.

Usage
    python watch_unknown.py --seconds 60                 # any VID_0000 node
    python watch_unknown.py --seconds 60 --match 05C6     # or anything else
    python watch_unknown.py --seconds 45 --all            # every USB node
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as _dt
import sys
import time

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_ALLCLASSES = 0x04
HDEVINFO = ctypes.c_void_p


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID),
                ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wt.DWORD)]


setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                          ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
setupapi.SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, wt.DWORD,
                                           ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    HDEVINFO, ctypes.POINTER(SP_DEVINFO_DATA), wt.LPWSTR, wt.DWORD,
    ctypes.POINTER(wt.DWORD)]
setupapi.SetupDiGetDevicePropertyW.argtypes = [
    HDEVINFO, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(DEVPROPKEY),
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), wt.DWORD]
setupapi.SetupDiGetDevicePropertyW.restype = wt.BOOL


def _pkey(d1: int, d2: int, d3: int, tail: tuple[int, ...], pid: int) -> DEVPROPKEY:
    return DEVPROPKEY(GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*tail)), pid)


# DEVPKEY_Device_LastArrivalDate {83da6326-97a6-4088-9453-a1923f573b29}, 102 (VT_FILETIME)
PKEY_ARRIVAL = _pkey(0x83DA6326, 0x97A6, 0x4088,
                     (0x94, 0x53, 0xA1, 0x92, 0x3F, 0x57, 0x3B, 0x29), 102)

_EPOCH = _dt.datetime(1601, 1, 1)


def _filetime_str(h, dev) -> str | None:
    ptype = wt.DWORD()
    raw = (ctypes.c_ubyte * 16)()
    size = wt.DWORD()
    ok = setupapi.SetupDiGetDevicePropertyW(
        h, ctypes.byref(dev), ctypes.byref(PKEY_ARRIVAL), ctypes.byref(ptype),
        raw, 16, ctypes.byref(size), 0)
    if not ok or size.value != 8:
        return None
    ft = int.from_bytes(bytes(raw)[:8], "little")
    if not ft:
        return None
    # FILETIME is UTC; convert to local or every comparison against the wall clock is
    # off by the UTC offset, which is how this first read as "an hour old" when the node
    # had actually arrived two minutes earlier.
    utc = (_EPOCH + _dt.timedelta(microseconds=ft / 10)).replace(tzinfo=_dt.timezone.utc)
    return utc.astimezone().strftime("%H:%M:%S.%f")[:-3]


def snapshot(match: str | None, everything: bool) -> dict[str, str | None]:
    """{instance_id: local arrival time} for every matching present device."""
    found: dict[str, str | None] = {}
    h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                      DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not h:
        return found
    try:
        idbuf = ctypes.create_unicode_buffer(1024)
        need = wt.DWORD()
        i = 0
        while True:
            dev = SP_DEVINFO_DATA()
            dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(h, i, ctypes.byref(dev)):
                break
            i += 1
            if not setupapi.SetupDiGetDeviceInstanceIdW(
                    h, ctypes.byref(dev), idbuf, 1024, ctypes.byref(need)):
                continue
            iid = idbuf.value
            up = iid.upper()
            if match:
                if match.upper() not in up:
                    continue
            elif everything:
                if not up.startswith("USB\\"):
                    continue
            elif "VID_0000" not in up:
                continue
            found[iid] = _filetime_str(h, dev)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--match", default=None,
                    help="substring to track (default: any VID_0000 node)")
    ap.add_argument("--all", action="store_true",
                    help="track every USB node instead of just the failed one")
    ap.add_argument("--poll", type=float, default=0.20)
    args = ap.parse_args()

    what = ("all USB nodes" if args.all
            else f'node matching "{args.match}"' if args.match else "failed VID_0000 node")
    print(f"tracking {what} for {args.seconds:.0f}s\n")

    t0 = time.time()
    prev: dict[str, str | None] | None = None
    changes = 0
    ever_seen = False
    arrivals: list[tuple[float, str, str | None, str]] = []

    while time.time() - t0 < args.seconds:
        cur = snapshot(args.match, args.all)
        if cur != prev:
            changes += 1
            ever_seen = ever_seen or bool(cur)
            if prev is None:
                print(f"[{time.time() - t0:6.2f}] initial: {len(cur)} node(s)")
                for iid, arr in cur.items():
                    print(f"           {iid}  arrived {arr}")
            else:
                for iid in cur.keys() - (prev or {}).keys():
                    arrivals.append((time.time() - t0, iid, cur[iid], "arrived"))
                    print(f"[{time.time() - t0:6.2f}] + ARRIVED {iid}  at {cur[iid]}")
                for iid in (prev or {}).keys() - cur.keys():
                    arrivals.append((time.time() - t0, iid, None, "left"))
                    print(f"[{time.time() - t0:6.2f}] - LEFT    {iid}")
                for iid in cur.keys() & (prev or {}).keys():
                    if cur[iid] != prev[iid]:
                        arrivals.append((time.time() - t0, iid, cur[iid], "rearrived"))
                        print(f"[{time.time() - t0:6.2f}] ~ RE-ARRIVED {iid}  at {cur[iid]}")
            prev = cur
        time.sleep(args.poll)

    print(f"\nchange events: {changes} (initial sample included)")
    re = [a for a in arrivals if a[3] in ("arrived", "rearrived")]
    gone = [a for a in arrivals if a[3] == "left"]
    if not ever_seen:
        print("  -> nothing matched during the window. The device is off the bus, or it")
        print("     came up as something this filter ignores.")
        return 0
    if not re and not gone:
        print("  -> STATIC. Nothing arrived, re-arrived or left. The node sat in the failed")
        print("     state for the whole window: the device stopped answering at the")
        print("     descriptor stage and is not retrying. Only power removal clears it.")
    else:
        print(f"  -> ACTIVE. {len(re)} arrival(s), {len(gone)} departure(s) in the window.")
        print("     The device is reaching USB address assignment and then failing (or")
        print("     succeeding as something new). That is a live bus, not a dead node.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
