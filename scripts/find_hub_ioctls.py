"""find_hub_ioctls.py - scan the USB hub IOCTL space for what this driver implements.

Why this exists
---------------
`IOCTL_USB_RESET_HUB` is accepted and does nothing: no re-enumeration, and the wedged
node's EnumerationRetryCount stays at 4. `IOCTL_USB_CYCLE_PORT` at 0x00220480 is
rejected with 87. One of those two numbers is wrong, and guessing again would repeat
the mistake that made every port in the machine read as "no device" earlier.

So this scans function ids and classifies the answer:

    ERROR_INVALID_FUNCTION (1)   the IOCTL does not exist at all
    ERROR_INVALID_PARAMETER (87) it exists but rejected these arguments
    OK                           it exists and accepted them

That classification is the point: an id that returns 87 is implemented, and if the
arguments are then wrong the way to find the right shape is to vary the buffer, not the
id. An id that returns 1 is a dead end.

Safety: these are hub configuration queries. The only ones with side effects are resets,
and the buffer sizes used here are the documented ones (a single ULONG port index). No
storage or device memory is touched.

Usage
    python find_hub_ioctls.py
    python find_hub_ioctls.py --hub "8&1b878445"
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys

import reset_port as R

ERR_INVALID_FUNCTION = 1
ERR_INVALID_PARAMETER = 87


def classify(ok: bool, err: int) -> str:
    if ok:
        return "OK"
    if err == ERR_INVALID_FUNCTION:
        return "missing"
    if err == ERR_INVALID_PARAMETER:
        return "exists/bad-args"
    return f"err={err}"


def call(h, code: int, port: int, insize: int = 4, outsize: int = 0):
    inbuf = ctypes.create_string_buffer(max(insize, 4))
    ctypes.cast(inbuf, ctypes.POINTER(wt.DWORD))[0] = port
    outbuf = ctypes.create_string_buffer(max(outsize, 4))
    returned = wt.DWORD()
    ok = R.kernel32.DeviceIoControl(h, code, inbuf, insize,
                                    outbuf if outsize else None, outsize,
                                    ctypes.byref(returned), None)
    return bool(ok), ctypes.get_last_error(), returned.value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=None, help="substring of the hub instance id")
    ap.add_argument("--from", dest="lo", type=int, default=256)
    ap.add_argument("--to", dest="hi", type=int, default=320)
    args = ap.parse_args()

    paths = R.hub_interface_paths()
    if args.hub:
        paths = [p for p in paths if args.hub.lower() in p.lower()]
    if not paths:
        print("no matching hub")
        return 2
    path = paths[0]
    print(path)
    print(f"administrator: {bool(ctypes.windll.shell32.IsUserAnAdmin())}\n")

    h, err = R.open_hub(path)
    if not h:
        print(f"cannot open hub (err {err})")
        return 2
    try:
        print(f"{'fid':>4}  {'code':10s}  in=4/out=0        in=4/out=4")
        print("-" * 56)
        for fid in range(args.lo, args.hi + 1):
            code = R.usb_ctl(fid)
            ok0, e0, r0 = call(h, code, 4, 4, 0)
            ok1, e1, r1 = call(h, code, 4, 4, 4)
            c0, c1 = classify(ok0, e0), classify(ok1, e1)
            if c0 == "missing" and c1 == "missing":
                continue          # not implemented; do not print 60 blank rows
            print(f"{fid:>4}  0x{code:08X}  {c0:16s}  {c1}")
    finally:
        R.CloseHandleSafe(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
