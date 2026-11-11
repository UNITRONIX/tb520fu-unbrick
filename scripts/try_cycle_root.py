"""try_cycle_root.py - does the USB 3.0 root hub accept a port cycle?

Why this is worth one more measurement
--------------------------------------
The tablet hangs off a USB 2.0 hub (`VID_1A40`), and `IOCTL_USB_CYCLE_PORT` refuses
every buffer shape there with 87. On the AMD root hub the same call returned
ERROR_NOT_SUPPORTED (50) - and 50 from a root hub is ambiguous: it can mean "this
hub does not implement it" or "you asked for a port it does not manage this way".

If a root-hub port cycle DOES work, then the tablet could be moved one socket to a
direct root port and every future un-wedge would be one command instead of a hand on
the cable. That is worth five minutes of measuring.

Safety: a port cycle on an empty port is a no-op. This script only targets a port it
has verified is empty, and it never cycles a port with a device on it.

Usage
    python try_cycle_root.py --find-free
    python try_cycle_root.py --port 2 --cycle
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

import reset_port as R


def state(h, port: int):
    return R.port_state(h, port)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--find-free", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--cycle", action="store_true")
    ap.add_argument("--hub", default="root_hub30")
    args = ap.parse_args()

    paths = [p for p in R.hub_interface_paths() if args.hub.lower() in p.lower()]
    if not paths:
        print("no matching hub")
        return 2

    print(f"administrator: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    for path in paths:
        h, err = R.open_hub(path)
        if not h:
            print(f"{path}\n  cannot open (err {err})")
            continue
        print(path)
        try:
            free: list[int] = []
            for port in range(1, 9):
                st = state(h, port)
                if st is None:
                    print(f"  port {port}: not queryable")
                    continue
                print(f"  port {port}: {R.describe(st['status']):<24} "
                      f"vid={st['vid']:04x} pid={st['pid']:04x}")
                if st["status"] == 0:
                    free.append(port)
            print(f"  empty ports: {free}")

            target = args.port
            if target is not None and target not in free:
                print(f"  refusing: port {target} is not empty")
                continue
            if args.cycle and target:
                ib = ctypes.create_string_buffer(16)
                ctypes.cast(ib, ctypes.POINTER(wt.DWORD))[0] = target
                ob = ctypes.create_string_buffer(16)
                ret = wt.DWORD()
                ok = R.kernel32.DeviceIoControl(
                    h, R.IOCTL_CYCLE_PORT, ib, 8, ob, 4, ctypes.byref(ret), None)
                e = ctypes.get_last_error()
                print(f"  CYCLE_PORT on empty port {target}: "
                      f"{'accepted' if ok else f'refused (err {e})'}")
                time.sleep(1.0)
        finally:
            R.CloseHandleSafe(h)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
