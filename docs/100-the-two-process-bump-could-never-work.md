# The two-process 900E -> 9008 procedure could never have worked

A defect in the tool, found while checking the device state, and why it explains a
whole class of "the bump stopped working" results.

---

## 1. What was checked, and the state

    10|```
14:38:52   node arrival (this plug)
14:39:14   no VID_05C6 node, COM1 only
           USB\VID_0000&PID_0002\9&1FF60AC4&0&4   Status Error, Code 43
14:39:34   retry accounting: EnumerationRetryCount=4, code=0x40010000
14:39:55   20 s window: no arrival, no departure
```

Vol+ at insertion wedged the device again, as in `docs/99`. Nothing new about the
    20|hardware here. But the state check raised a different question - *what would we
even run if a HELLO appeared?* - and reading the answer turned up a bug.

## 2. The defect

`docs/38` §3 gives the working command sequence:

```
python scripts/tablet.py selftest
python scripts/tablet.py bump
python scripts/tablet.py wait --want 9008 --seconds 60
```

and `catch` printed, on seeing a crashdump HELLO:

```
*** HELLO ver=2 mode=2 ***
crashdump HELLO. Run `bump` now, or `read` for memory.
    30|
```

**`bump` in a second process cannot work, ever.** It calls `open_900e()`, opens a NEW
handle, and waits up to 5 s for a HELLO - but the HELLO is consumed by the first
opener (`docs/34`), and `catch` just consumed it. By the time the advice is printed,
the packet is gone. The only session that can switch is the one holding it.

The same defect in `bump` itself: it printed "switch complete; 9008 should enumerate
in ~20 s", closed the handle, and returned. The 9008 node then emits a **new**
ver=3 mode=0 HELLO, and that HELLO is also first-opener-wins. Running `wait --want
9008` polls PIDs and never opens the port, so the HELLO sat there until something
else took it - which is exactly the "port open, no bytes pending" result recorded
over and over (`docs/52`, `docs/87`).

So the repository documented a procedure whose two halves were both unreachable from
    40|the process that printed them. Any attempt that followed the documentation was
guaranteed to reach 9008 and then lose it.

## 3. The fix

`switch_to_edl(link, ver)` is now a function, and both callers use it **on the live
handle**:

- `catch` - reads the HELLO, and if it is mode=2, switches immediately on the same
  connection, then races for the 9008 HELLO. `--no-bump` restores report-only.
- `bump` - switches, then by default chains into the 9008 grab (`--no-grab` opts out).

   50|`grab_edl_hello(timeout)` is the new second half: it polls the **port list**
directly (`list_ports`, single-digit ms) instead of the PID table via a PowerShell
round-trip (~400 ms), then opens and reads at once. It also names the other failure
mode instead of timing out on it:

```
9008 node IS on the bus but has no COM port
-> WinUSB owns it; run Switch-DeviceDriver.ps1 -To COM (elevated)
```

That distinction matters because a 9008 node under libwdi's WinUSB package has no COM
port at all; waiting longer cannot help, and the old code just said "never appeared".

## 4. How it is verified, and how it is not

`scripts/test_switch_flow.py` runs the exchange against a fake `Link` that replays the
documented device replies. It checks the things that are easy to get silently wrong:

    70|| check | why it is there |
|---|---|
| 4 writes in the right order | HELLO_RSP, SWITCH_MODE, HELLO_RSP, DONE |
| `SWITCH_MODE` declares len=12, not 16 | 12 is the form with log evidence (docs/14 V1b) |
| the confirming HELLO_RSP echoes **ver=3**, not ver=2 | the fresh HELLO is a different version; echoing 2 is a real protocol error |
| refusal paths send nothing further | no DONE after a refused switch |

All pass. **What this does not prove:** that the tablet answers this way. The test
proves the host half only. `docs/97` is the standing rule - the device half is only
proven by a real run with a captured HELLO.

## 5. What is still needed

A fresh boot that produces a mode=2 HELLO with the handle already held:

```
python scripts/tablet.py catch --seconds 180
```

That single command now covers route (a) end to end: hold, read, switch, then grab the
9008 HELLO. No second process, no second guess.

    90|The blocker is unchanged and physical: the tablet is wedged
(`EnumerationRetryCount=4`, Windows stopped asking), and it needs power removed before
it will enumerate again. Vol+ at insertion produces this state - 2 for 2 - so the next
attempt should hold nothing.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

New in this document: the documented procedure was not merely fragile, it was
impossible as written, and that is now fixed and tested on the host side.
