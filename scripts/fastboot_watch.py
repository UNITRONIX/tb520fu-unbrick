#!/usr/bin/env python3
"""Watch for ANY new USB device - specifically a fastboot interface.

Why this is different from earlier attempts
-------------------------------------------
Every previous watcher looked for the device to come back as a *known* PID and
gave up in seconds. But:

  * fastboot PERSISTS once entered - there is no microsecond race to win.
    The ABL sits in fastboot until told to boot. So a 50 ms poll is plenty.
  * The ABL's fastboot interface is NOT 05C6:9008/900E. Qualcomm ABL fastboot
    usually enumerates as 18D1:4EE0, 18D1:D00D, 05C6:901D or 05C6:9091.
    A filter on 05C6 alone would have missed it - which may be exactly what
    happened before.

So: enumerate EVERYTHING, print every VID:PID ever seen, and shout when a new
one appears. Read-only - it never opens or writes the device.

Usage
    python fastboot_watch.py --time 600
"""
from __future__ import annotations

import argparse
import sys
import time

import usb.core

T0 = time.time()

# PIDs that mean "bootloader / fastboot / download"
FASTBOOT_IDS = {
    (0x18D1, 0x4EE0): "Google fastboot",
    (0x18D1, 0x4EE1): "Google fastboot (alt)",
    (0x18D1, 0xD00D): "Google fastbootd",
    (0x05C6, 0x901D): "Qualcomm fastboot",
    (0x05C6, 0x9091): "Qualcomm fastboot (alt)",
    (0x05C6, 0x9008): "Qualcomm EDL",
    (0x05C6, 0x900E): "Qualcomm crashdump",
    (0x17EF, 0x7ED7): "Lenovo ADB",
    (0x17EF, 0x0001): "Lenovo (unknown)",
}


def log(msg: str) -> None:
    print(f"[{time.time() - T0:8.2f}] {msg}", flush=True)


def snapshot() -> dict[tuple[int, int], str]:
    """All USB devices as {(vid,pid): 'vid:pid bus/addr'}."""
    out: dict[tuple[int, int], str] = {}
    try:
        for d in usb.core.find(find_all=True):
            key = (d.idVendor, d.idProduct)
            out[key] = f"{d.idVendor:04x}:{d.idProduct:04x} bus{d.bus} adr{d.address}"
    except Exception as err:  # noqa: BLE001
        log(f"enumerate exc {type(err).__name__}: {err}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=600.0)
    args = ap.parse_args()

    log("=" * 68)
    log("#  fastboot watch - nasluch na DOWOLNE nowe urzadzenie USB")
    log("=" * 68)

    base = snapshot()
    log(f"baseline: {len(base)} urzadzen")
    for (vid, pid), desc in sorted(base.items()):
        name = FASTBOOT_IDS.get((vid, pid), "")
        log(f"   {desc}  {name}")

    log("")
    log("Czekam na nowe urzadzenie. Zrob na tablecie sekwencje klawiszy.")
    log("")

    seen = dict(base)
    new_nodes: list[str] = []
    found_fastboot = False
    last_report = time.time()
    deadline = time.time() + args.time

    while time.time() < deadline:
        cur = snapshot()

        for key, desc in cur.items():
            if key not in seen:
                seen[key] = desc
                vid, pid = key
                name = FASTBOOT_IDS.get(key, "NIEZNANE")
                star = ""
                if key in FASTBOOT_IDS and "fastboot" in FASTBOOT_IDS[key].lower():
                    star = "   <<<<< FASTBOOT >>>>>"
                    found_fastboot = True
                log(f"+ NOWE  {desc}  {name}{star}")
                new_nodes.append(f"{desc} {name}")
            else:
                seen[key] = desc

        gone = [k for k in seen if k not in cur]
        for key in gone:
            vid, pid = key
            name = FASTBOOT_IDS.get(key, "")
            log(f"- ZNIK  {seen.pop(key)}  {name}")

        # heartbeat so we know the loop is alive
        if time.time() - last_report > 15.0:
            log(f"  ... nasluch dalej ({len(cur)} urzadzen)")
            last_report = time.time()

        time.sleep(0.05)

    log("")
    log("=" * 68)
    log("#  WYNIK")
    log("=" * 68)
    log(f"nowych wezlow: {len(new_nodes)}")
    for n in new_nodes:
        log(f"   {n}")
    log("")
    if found_fastboot:
        log(">>> FASTBOOT SIE POJAWIL. Droga jest otwarta.")
        log(">>> Nastepny krok: fastboot flash abl_a/abl_b stockiem.")
    elif new_nodes:
        log(">>> Pojawialy sie nowe wezly - sprawdz liste powyzej.")
    else:
        log(">>> ZADNEGO nowego urzadzenia przez caly czas nasluchu.")
        log(">>> ABL nie wystawil fastboot - patrz wniosek w raporcie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
