"""probe_hub_ioctl.py - which hub IOCTLs work unelevated, and what each returns.

Context
-------
`IOCTL_USB_CYCLE_PORT` answers ERROR_INVALID_PARAMETER (87) from a non-elevated
process. That is ambiguous: it can mean "needs admin" or "this hub does not implement
it". `IOCTL_USB_RESET_HUB` is a different call with a different contract, so this
probes both, at several buffer sizes and access masks, and reports the pair
(ok, GetLastError) for each - which is enough to tell the two cases apart.

Why a file rather than a one-liner
----------------------------------
The inline version of this died on a ctypes type error from a conditional expression
that mixed a kernel32 HANDLE with a Python int. The lesson is the same one that has
cost time twice in this project: probing Win32 through a shell one-liner gives you
errors you then have to debug blind. Put it in a file, give it types, run it once.

Usage
    python probe_hub_ioctl.py
    python probe_hub_ioctl.py --hub "8&1b878445" --port 4
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys

import reset_port as R


def open_with_access(path: str, access: int):
    h = R.kernel32.CreateFileW(path, access,
                               R.FILE_SHARE_READ | R.FILE_SHARE_WRITE,
                               None, R.OPEN_EXISTING, 0, None)
    if not h or h == R.INVALID_HANDLE_VALUE:
        return None, ctypes.get_last_error()
    return h, 0


def call(h, code: int, port: int, insize: int, outsize: int) -> tuple[bool, int]:
    inbuf = ctypes.create_string_buffer(max(insize, 4))
    ctypes.cast(inbuf, ctypes.POINTER(wt.DWORD))[0] = port
    outbuf = ctypes.create_string_buffer(max(outsize, 4))
    returned = wt.DWORD()
    ok = R.kernel32.DeviceIoControl(
        h, code,
        inbuf if insize else None, insize,
        outbuf if outsize else None, outsize,
        ctypes.byref(returned), None)
    return bool(ok), ctypes.get_last_error()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=None, help="substring of the hub instance id")
    ap.add_argument("--port", type=int, default=4)
    args = ap.parse_args()

    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"administrator: {is_admin}\n")

    paths = R.hub_interface_paths()
    if args.hub:
        paths = [p for p in paths if args.hub.lower() in p.lower()]
    if not paths:
        print("no matching hub interface")
        return 2

    for path in paths:
        print(path)
        for access, label in ((R.GENERIC_READ | R.GENERIC_WRITE, "RW"),
                              (R.GENERIC_READ, "R")):
            h, err = open_with_access(path, access)
            if not h:
                print(f"  {label}: cannot open (err {err})")
                continue
            try:
                for code, name in ((R.IOCTL_RESET_HUB, "RESET_HUB"),
                                   (R.IOCTL_CYCLE_PORT, "CYCLE_PORT")):
                    for insize, outsize in ((4, 0), (4, 4), (8, 0)):
                        ok, e = call(h, code, args.port, insize, outsize)
                        print(f"  {label} {name:11s} 0x{code:08X} "
                              f"in={insize} out={outsize}: "
                              f"{'OK' if ok else f'refused err={e}'}")
            finally:
                R.CloseHandleSafe(h)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
