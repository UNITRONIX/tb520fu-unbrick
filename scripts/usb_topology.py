"""usb_topology.py - where exactly is the tablet hanging off the USB tree?

Why this exists
---------------
`docs/91` and `docs/94` established that the tablet sat behind THREE hubs, and `docs/98`
recorded the one success in this whole effort: on a direct root-hub port the tablet came up
as `05C6:900E` with a working COM port, and through the hub chain it did not. That makes
"which port is it on" a first-class input to every experiment, not trivia - and yet it kept
being discovered after the fact.

This tool prints the full ancestry of a node: root hub -> hub -> hub -> device, with the
USB address and port number at each hop, plus how many hubs are in between.

Usage
    python usb_topology.py                  # auto-find the tablet (05C6, else VID_0000)
    python usb_topology.py --instance "USB\\VID_0000&PID_0002\\9&1FF60AC4&0&4"
    python usb_topology.py --all-tablets
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)

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

cfgmgr32.CM_Get_DevNode_Registry_PropertyW.argtypes = [
    wt.DWORD, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
    ctypes.POINTER(wt.DWORD), wt.DWORD]
cfgmgr32.CM_Get_DevNode_Registry_PropertyW.restype = wt.DWORD

CM_DRP_DEVICEDESC = 0x00
CM_DRP_LOCATION_INFORMATION = 0x0D


def _pkey(d1, d2, d3, tail, pid) -> DEVPROPKEY:
    return DEVPROPKEY(GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*tail)), pid)


PKEY_ADDRESS = _pkey(0xA35996AB, 0x11CF, 0x4935,
                     (0x8B, 0x61, 0xA6, 0x76, 0x10, 0x81, 0xEC, 0xDF), 5)
PKEY_PARENT = _pkey(0x4340A6C5, 0x93FA, 0x4706,
                    (0x97, 0x2C, 0x7B, 0x64, 0x80, 0x08, 0xA5, 0xA7), 8)


def _prop_str(h, dev, key) -> str | None:
    ptype = wt.DWORD()
    raw = ctypes.create_unicode_buffer(2048)
    size = wt.DWORD()
    ok = setupapi.SetupDiGetDevicePropertyW(
        h, ctypes.byref(dev), ctypes.byref(key), ctypes.byref(ptype),
        raw, 4096, ctypes.byref(size), 0)
    if not ok:
        return None
    s = raw.value
    # DEVPKEY_Device_Parent comes back as "USB\VID_..\..\DEVINST\4&1a2b3c&0&0";
    # strip the trailing \DEVINST\... so it compares to instance ids.
    return s


def _reg_str(devinst: int, prop: int) -> str | None:
    buf = ctypes.create_unicode_buffer(1024)
    size = wt.DWORD(2048)
    rc = cfgmgr32.CM_Get_DevNode_Registry_PropertyW(
        devinst, prop, None, buf, ctypes.byref(size), 0)
    return buf.value if rc == 0 else None


def enumerate_usb() -> dict[str, tuple[int, str | None, str | None]]:
    """{UPPERCASE instance_id: (devinst, usb address or None, parent instance id or None)}

    Keys are upper-cased because Windows reports instance ids with varying case
    (`7&14c6e8ad` vs `7&14C6E8AD`), and a case-sensitive dict lookup silently truncates
    the ancestry at the first hop - which is exactly how an earlier version reported a
    3-hub chain as a direct connection.
    """
    out: dict[str, tuple[int, str | None, str | None]] = {}
    h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                      DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not h:
        return out
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
            if not iid.upper().startswith("USB\\"):
                continue
            addr = None
            ptype = wt.DWORD()
            raw = (ctypes.c_ubyte * 8)()
            size = wt.DWORD()
            if setupapi.SetupDiGetDevicePropertyW(
                    h, ctypes.byref(dev), ctypes.byref(PKEY_ADDRESS),
                    ctypes.byref(ptype), raw, 8, ctypes.byref(size), 0):
                addr = int.from_bytes(bytes(raw)[:size.value], "little")
            parent = _prop_str(h, dev, PKEY_PARENT)
            if parent and "\\DEVINST\\" in parent:
                parent = parent.split("\\DEVINST\\")[0]
            out[iid.upper()] = (dev.DevInst, addr, parent.upper() if parent else None)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return out


def label(iid: str, table) -> str:
    entry = table.get(iid)
    addr = entry[1] if entry else None
    desc = _reg_str(entry[0], CM_DRP_DEVICEDESC) if entry else None
    loc = _reg_str(entry[0], CM_DRP_LOCATION_INFORMATION) if entry else None
    bits = [iid]
    if addr is not None:
        bits.append(f"addr={addr}")
    if loc:
        bits.append(f"({loc})")
    if desc:
        bits.append(f"[{desc}]")
    return "  ".join(bits)


def chain(iid: str, table) -> list[tuple[str, int]]:
    """Root-first list of (instance_id, hop index) ending at `iid`."""
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    cur = iid
    while cur and cur not in seen:
        seen.add(cur)
        out.append((cur, len(out)))
        entry = table.get(cur)
        cur = entry[2] if entry and entry[2] else ""
    out.reverse()
    return out


def is_hub(iid: str) -> bool:
    up = iid.upper()
    return ("ROOT_HUB" in up) or ("VID_1A40" in up) or ("VID_0A05" in up) or ("HUB" in up)


def report(iid: str, table) -> int:
    hops = chain(iid, table)
    ancestors = [h for h, _ in hops[:-1]]
    # Depth = hub hops BETWEEN the root hub and the device. A device whose parent IS the
    # root hub is direct (0). Counting every hub in the ancestry instead made a one-hub
    # chain print as "2 hubs in the path", double-reporting the root hub.
    intermediates = [a for a in ancestors
                     if is_hub(a) and "ROOT_HUB" not in a.upper()]
    print(f"\n{iid}")
    for node, _ in hops:
        mark = "  " if node != iid else "->"
        print(f"  {mark} {label(node, table)}")
    if not intermediates:
        print("  depth: 0 - DIRECT root-hub port (the configuration that worked in docs/98)")
        return 0
    print(f"  depth: {len(intermediates)} intermediate hub(s) - "
          f"docs/94 and docs/98 say this is where the tablet wedges")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default=None)
    ap.add_argument("--all-tablets", action="store_true")
    args = ap.parse_args()

    table = enumerate_usb()
    if not table:
        print("nothing enumerable under USB\\ - enumeration itself failed", file=sys.stderr)
        return 2

    targets: list[str]
    if args.instance:
        key = args.instance.upper()
        matches = [k for k in table if k == key]
        if not matches:
            print(f"not present: {args.instance}", file=sys.stderr)
            for k in sorted(table):
                if "05C6" in k or "VID_0000" in k:
                    print(f"  candidate: {k}", file=sys.stderr)
            return 2
        targets = matches
    else:
        qc = [k for k in table if "VID_05C6" in k]
        unk = [k for k in table if "VID_0000" in k]
        targets = qc + unk if args.all_tablets else (qc or unk or [])
        if not targets:
            print("no 05C6 (Qualcomm) node and no VID_0000 node present.")
            print("USB tree root hubs:")
            for k in sorted(table):
                if "ROOT_HUB" in k:
                    print(f"  {label(k, table)}")
            return 1

    rc = 0
    for t in targets:
        rc |= report(t, table)
    return rc


if __name__ == "__main__":
    sys.exit(main())
