"""usb_history.py - when did each tablet USB identity first appear, and where?

Why this exists
---------------
The question "did the wedge start at a particular attempt, or has it always been the
default?" has been answered from memory and from prose in several documents. The registry
holds the answer directly: every instance a device has ever enumerated as keeps a record,
and its `ContainerID` is a version-1 GUID whose timestamp is when that container was
created - i.e. when the device first appeared in that identity.

That makes it possible to lay out, on one timeline, when this tablet was seen as
`9008`, as `900E`, and as the wedged `VID_0000&PID_0002` - and to see which of those
came first and how they interleave.

Why a separate script rather than a one-liner: the escaping needed to run this through
PowerShell from a Python string is exactly the kind of thing that silently produces zero
rows and a confident conclusion about an empty result.

Usage
    python usb_history.py
    python usb_history.py --vid 05C6         # only Qualcomm records
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import struct
import sys
import winreg

BASE = r"SYSTEM\CurrentControlSet\Enum\USB"
EPOCH_V1 = dt.datetime(1582, 10, 15)     # GUID v1 timestamps count from here


def guid_v1_time(guid: str | None) -> dt.datetime | None:
    """Timestamp from a version-1 GUID string; None for anything else."""
    if not guid:
        return None
    try:
        d1, d2, d3, d4, d5 = guid.strip("{}").split("-")
        tl = int(d1, 16)
        tm = int(d2, 16)
        th = int(d3, 16)
        # Clear the version nibble: 0x1 for a time-based GUID.
        th &= 0x0FFF
        ts = (th << 48) | (tm << 32) | tl
        return EPOCH_V1 + dt.timedelta(microseconds=ts / 10)
    except Exception:  # noqa: BLE001
        return None


def read_values(path: str) -> dict[str, object]:
    out: dict[str, object] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                out[name] = value
    except OSError:
        pass
    return out


def enum_children(path: str) -> list[str]:
    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return names


def describe(value: object) -> str:
    """DeviceDesc comes as '@inf,%key%;Human text' - keep the human part."""
    if not isinstance(value, str):
        return ""
    if ";" in value:
        return value.split(";", 1)[1]
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", default=None, help="only VIDs containing this substring")
    args = ap.parse_args()

    rows: list[tuple[dt.datetime, str, str, str, str]] = []
    for vid_key in enum_children(BASE):
        if args.vid and args.vid.upper() not in vid_key.upper():
            continue
        if not vid_key.upper().startswith("VID_"):
            continue
        for inst in enum_children(f"{BASE}\\{vid_key}"):
            path = f"{BASE}\\{vid_key}\\{inst}"
            vals = read_values(path)
            dp = read_values(f"{path}\\Device Parameters")
            when = guid_v1_time(vals.get("ContainerID"))
            if when is None:
                continue
            rows.append((
                when,
                f"{vid_key}\\{inst}",
                str(vals.get("LocationInformation") or ""),
                str(dp.get("PortName") or ""),
                describe(vals.get("DeviceDesc")),
            ))

    rows.sort()
    print(f"{len(rows)} records with a version-1 ContainerID\n")
    width = max((len(r[1]) for r in rows), default=20)
    print(f"{'first seen':19s}  {'identity':{width}s}  {'location':22s}  port  description")
    print("-" * (19 + width + 22 + 30))
    for when, ident, loc, port, desc in rows:
        print(f"{when.strftime('%Y-%m-%d %H:%M:%S')}  {ident:{width}s}  "
              f"{loc:22s}  {port:5s} {desc}")

    # The tablet's own identities, in the order they first appeared.
    mine = [r for r in rows
            if "VID_0000&PID_0002" in r[1]
            or "PID_9008" in r[1] or "PID_900E" in r[1]]
    if mine:
        print("\ntablet identities, chronological:")
        for when, ident, loc, port, _ in mine:
            print(f"  {when.strftime('%m-%d %H:%M')}  {ident}  {port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
