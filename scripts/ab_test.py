#!/usr/bin/env python3
"""ab_test.py - run the Volume Up + Volume Down question as a controlled A/B, not a guess.

The problem this solves
-----------------------
On 2026-11-11 the both-volume-keys procedure produced a different USB outcome
(`VID_0000&PID_0002` instead of `900E`), and it was impossible to tell whether the
keys caused it, because the cable was also moved during the attempt (docs/85).

Changing two things at once is the error this script exists to prevent. It runs the
same physical procedure twice - once with no keys (control), once with both keys
(test) - and reports the outcome of each, so the comparison is mechanical.

What it records
---------------
For each run: whether the device left the bus, how long it was gone, exactly what
node appeared, and what state it settled into after settling time. Results go to
ab_test.json so the two runs can be compared without relying on memory.

What the operator does (the script prompts at the right moments)
---------------------------------------------------------------
    CONTROL   unplug, power down, insert cable with NO keys held
    TEST      unplug, power down, insert cable holding BOTH volume keys

Read-only: enumerates USB and reads one packet if a Qualcomm port appears.

Usage
    python ab_test.py --run control
    python ab_test.py --run test
    python ab_test.py --compare
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "ab_test.json"

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
    print(m, flush=True)


def usb_nodes() -> frozenset[str]:
    """Every USB device instance id. No VID filter - a wedged node has none."""
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
                if s.upper().startswith("USB\\") or "VID_" in s.upper():
                    found.add(s)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return frozenset(found)


def tablet_nodes() -> list[str]:
    return sorted(n for n in usb_nodes()
                  if "VID_05C6" in n.upper() or "VID_0000" in n.upper())


def classify(nodes: list[str]) -> str:
    """Turn the set of tablet-ish nodes into a verdict string."""
    if not nodes:
        return "absent"
    pids = []
    for n in nodes:
        up = n.upper()
        i = up.find("PID_")
        pids.append(up[i + 4:i + 8] if i >= 0 else "?")
    if "9008" in pids:
        return "EDL-9008"
    if "900E" in pids:
        return "crashdump-900E"
    if all(p == "0002" for p in pids):
        return "wedged-0000:0002"
    return "other:" + ",".join(pids)


def read_hello() -> str:
    """If a Qualcomm COM port exists, report the first packet without writing."""
    import serial.tools.list_ports
    cands = [p.device for p in serial.tools.list_ports.comports()
             if "05C6" in (p.hwid or "").upper()
             or "QUALCOMM" in (p.description or "").upper()]
    if not cands:
        return "no Qualcomm COM port"
    try:
        import serial
        with serial.Serial(cands[0], 115200, timeout=0.3) as s:
            data = s.read(64)
    except Exception as err:  # noqa: BLE001
        return f"{cands[0]} could not be opened ({type(err).__name__})"
    if not data:
        return f"{cands[0]} open, no bytes pending"
    if len(data) >= 8:
        cmd, ln = struct.unpack_from("<II", data, 0)
        if cmd == 0x01 and len(data) >= 0x30:
            ver = struct.unpack_from("<I", data, 8)[0]
            mode = struct.unpack_from("<I", data, 20)[0]
            return f"*** HELLO ver={ver} mode={mode} ***"
        return f"packet cmd={cmd:#x} len={ln}"
    return f"{len(data)} bytes"


def run(label: str, seconds: float) -> int:
    log("=" * 72)
    log(f"#  A/B run: {label.upper()}")
    log("=" * 72)

    if label == "control":
        log("")
        log("  Do this, with NO keys held:")
        log("    1. unplug the USB cable")
        log("    2. hold Power 20-30 s until the screen is dark")
        log("    3. plug the cable back in, touching no keys")
        log("    4. wait")
    else:
        log("")
        log("  Do this, holding BOTH volume keys:")
        log("    1. unplug the USB cable")
        log("    2. hold Power 20-30 s until the screen is dark")
        log("    3. hold Volume UP and Volume DOWN together")
        log("    4. keeping both held, plug the cable in")
        log("    5. keep holding ~10 s, then release")
    log("")

    before = tablet_nodes()
    log(f"  before: {classify(before)}  {before or ''}")
    log("  watching...")

    left_at = None
    appeared = None
    end = time.time() + seconds
    while time.time() < end:
        now_nodes = tablet_nodes()
        if left_at is None and not now_nodes:
            left_at = time.time()
            log("  - device left the bus")
        if left_at is not None and now_nodes and appeared is None:
            appeared = time.time()
            log(f"  + node appeared: {now_nodes}")
            log("    (waiting to see if it settles)")
        time.sleep(0.05)

    # settle, then take the verdict
    time.sleep(2.0)
    final_nodes = tablet_nodes()
    verdict = classify(final_nodes)
    hello = read_hello()

    log("")
    log(f"  absent for   : {('%.1f s' % (appeared - left_at)) if (left_at and appeared) else 'n/a'}")
    log(f"  final nodes  : {final_nodes or 'none'}")
    log(f"  VERDICT      : {verdict}")
    log(f"  port         : {hello}")

    rec = {}
    if OUT.exists():
        try:
            rec = json.loads(OUT.read_text())
        except Exception:  # noqa: BLE001
            rec = {}
    rec[label] = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "before": before,
        "absent_s": round(appeared - left_at, 1) if (left_at and appeared) else None,
        "final_nodes": final_nodes,
        "verdict": verdict,
        "hello": hello,
    }
    OUT.write_text(json.dumps(rec, indent=2))
    log(f"  saved to {OUT}")
    return 0 if verdict == "EDL-9008" else 1


def compare() -> int:
    if not OUT.exists():
        log("no results yet")
        return 1
    rec = json.loads(OUT.read_text())
    if "control" not in rec or "test" not in rec:
        log(f"need both runs; have: {sorted(rec)}")
        return 1
    c, t = rec["control"], rec["test"]
    log("=" * 72)
    log("#  Comparison")
    log("=" * 72)
    log(f"  control : {c['verdict']:<18} absent {c['absent_s']} s   {c['hello']}")
    log(f"  test    : {t['verdict']:<18} absent {t['absent_s']} s   {t['hello']}")
    log("")
    if c["verdict"] == t["verdict"]:
        log("  SAME OUTCOME -> the keys made no difference.")
        log("  The earlier VID_0000&PID_0002 result was a replug artefact, not the keys.")
    elif t["verdict"] == "EDL-9008":
        log("  *** THE KEYS REACHED EDL. This is the state the goal asks for. ***")
    elif c["verdict"] == "crashdump-900E" and t["verdict"].startswith("wedged"):
        log("  DIFFERENT OUTCOME, and only the keys differ.")
        log("  -> the keys ARE being read, and they push the device into a state it")
        log("     cannot finish enumerating. That is progress even though it is not EDL:")
        log("     the PON input is live, so the next step is finding the combination that")
        log("     completes instead of wedging.")
    else:
        log("  DIFFERENT OUTCOME. Worth repeating both runs to confirm it is stable.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", choices=["control", "test"])
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        return compare()
    if not args.run:
        log("give --run control, --run test, or --compare")
        return 2
    return run(args.run, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
