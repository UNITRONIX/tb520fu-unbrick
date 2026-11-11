# The untested key combination: Volume Up together with Volume Down

Of all the entry methods examined in this session, one has never been tried, and the
evidence for it is stronger than for several that were.

---

## 1. What was actually tested

`docs\07` §D2 lists exactly four attempts:

```
Vol+   |   Vol−   |   Vol+ with Power   |   Vol− with Power
```

**"Volume Up together with Volume Down" does not appear.** Verified by searching the whole
repository for that combination - the only hits are in `scripts/pon_probe.py`, where it
appears as a *status code name*, not as a tested procedure.

## 2. Why the combination is different from the individual keys

`pon_probe.py` names the PMIC PON reason codes:

```
0  PON_KPDPWR          power key only
1  PON_RESIN           resin only
2  PON_KPDPWR_RESIN    BOTH KEYS
```

**The PMIC has a distinct state for both keys together.** It is not the union of the two
individual states - it is its own code.

And `docs\07` §D2's correction established which keys the PON block sees:

```
Volume Down  ->  pon_resin            PMIC PON input, identical on every Qualcomm platform
Volume Up    ->  PM8550 gpio6         needs a driver to be read
Power        ->  pon_pwrkey           PMIC PON input
```

So:

| combination | read by | works on this tablet? |
|---|---|---|
| Vol+ alone | PM8550 gpio6, needs driver | **no** - driver never loads (`docs\47`) |
| Vol− alone | PON resin | yes, but does not trigger EDL |
| **Vol+ and Vol− together** | **PON KPDPWR_RESIN** | **untested** |

That is the point: **the combination may be visible to the PON block even though Vol+ alone
is not visible at all.** The PMIC does not need the SoC GPIO driver to notice that its resin
input is asserted while the power key path is also active.

## 3. Why it is the standard procedure for this model

An external instruction page for flashing a **TB520FU** gives, as the primary method:

> Turn off your device. Hold down the **volume up and volume down buttons simultaneously**.
> While holding the volume buttons, connect your device to your computer via USB cable.
> Your device should now be in EDL mode.
> *Note: if still not in EDL mode then you have to short test point.*

So the model-specific guidance names **both volume keys together** as the first attempt and
the test point as the fallback. `docs\07` §D2 tried each key separately and with Power, but
never the pair.

## 4. The exact procedure

```
1. unplug the USB cable
2. hold Power until the screen goes dark and stays dark
3. hold BOTH volume keys
4. while holding both, insert the cable
5. keep holding ~10 s
6. release
```

Verification: `python scripts/tablet.py watch` logs every USB device that appears or
disappears with no VID filter, so whatever the device enumerates as will be seen.

## 5. Honest assessment

- **It is a real possibility, not a promise.** `docs\07` §D2's deeper correction is still
  true: the ROCKNIX ABL never reaches its key-reading decision point, so a key held after
  power-on may be ignored regardless of which PMIC input it lands on.
- **But the PON angle is new.** The earlier conclusion was about *the ABL reading keys*. The
  PON block is read by PMIC hardware and by the boot ROM, before any ABL exists - and
  `docs\43`'s vendor card explicitly describes an entry that happens in the **off** state.
- **It costs nothing.** No disassembly, no soldering, no risk beyond what a normal boot does.
- **It can be repeated.** If it fails, the device state is unchanged and the watcher records
  a negative.

Given that three register-level routes are provably closed (`docs\70`, `docs\71`,
`docs\80`), a free physical attempt with model-specific precedent deserves to be made
before the case is opened.

## 6. Status

Goal `HELLO ver=3 mode=0`: **not achieved.** Device verified present as `PID_900E`, `COM10`
open, no HELLO. No process holding the port.

This document exists because the combination is the last cheap thing not yet tried, and
because the reason it might work - a distinct PMIC state, not two GPIO reads - is specific
and checkable rather than hopeful.
