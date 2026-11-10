#!/usr/bin/env python3
"""Characterise the boot loop: how long is the device present / absent?

Earlier measurements recorded ~15 s absent (logo phase) then ~40 s present.
After the Power+Vol- attempt one cycle showed only 3 s absent. If that repeats,
the device is taking a different boot path - which is the first behavioural
change ever observed on this unit, and worth pinning down.
"""
from __future__ import annotations
import sys, time
import usb.core

T0 = time.time()

def log(m):
    print(f"[{time.time()-T0:7.2f}] {m}", flush=True)

def find():
    return usb.core.find(idVendor=0x05C6, idProduct=0x900E) is not None

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
log("=" * 60)
log("#  cycle timing - obecny / nieobecny")
log("=" * 60)

state = find()
log(f"start: {'OBECNY 900E' if state else 'nieobecny'}")
t_change = time.time()
cycles = []

end = time.time() + dur
while time.time() < end:
    now = find()
    if now != state:
        gap = time.time() - t_change
        cycles.append((state, gap))
        log(f"-> {'OBECNY ' if now else 'NIEOBECNY'}   "
            f"(poprzedni stan trwal {gap:5.2f} s)")
        state = now
        t_change = time.time()
    time.sleep(0.02)

present = [g for s, g in cycles if s]
absent = [g for s, g in cycles if not s]
log("")
log("=" * 60)
log(f"zmian stanu: {len(cycles)}")
if absent:
    log(f"NIEOBECNY: n={len(absent)}  min={min(absent):.2f}  max={max(absent):.2f}  "
        f"srednia={sum(absent)/len(absent):.2f}")
if present:
    log(f"OBECNY   : n={len(present)}  min={min(present):.2f}  max={max(present):.2f}  "
        f"srednia={sum(present)/len(present):.2f}")
log("")
if absent and max(absent) < 8:
    log(">>> Krotkie okna nieobecnosci (<8 s): brak fazy logo.")
    log(">>> Urzadzenie pada szybciej niz w poprzednich pomiarach (15 s).")
elif absent:
    log(">>> Okna nieobecnosci >=8 s: faza logo nadal wystepuje.")
