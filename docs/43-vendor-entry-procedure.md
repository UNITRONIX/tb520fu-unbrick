# The vendor's own entry procedure: power off, hold Volume Up, plug in

`pics/Volume up.JPG` in the Lenovo RSA package is an instruction card, not a
photo of hardware. It says:

> **In power off status, keep Volume up key pressing and then connect device to
> computer.**
>
> If no COM port device list below, please try again.

This is the fourth entry procedure in this repository, and it is the only one that
comes from the manufacturer. It differs from everything tried so far in one
decisive way.

---

    15|## 1. Why the previous key attempts do not rule this out

`07-dead-ends.md` §D2 records that Volume Up / Down / combinations produced no
readable input, and a later correction narrowed that to "the ABL never reaches its
menu decision point".

Both statements are about the **ABL menu** — a bootloader running from UFS,
reading keys after power-on. The vendor instruction is not that:

| | keys tried before | vendor procedure |
|---|---|---|
| device state | powering on, booting | **powered off** |
| when the key is held | during / after boot | **before and during cable insertion** |
| what reads the key | ABL, from UFS | **boot ROM / charger logic, before any image loads** |
| expected result | a menu, or fastboot | **a COM port** |

So §D2 is not contradicted. It tested a different reader, in a different state,
for a different output.

## 2. Why "powered off" is the hard part

`07-dead-ends.md` §E2 states the tablet "cannot be powered off — power always
returns to logo, then crashdump", and every cycle in this repository has been a
key-hold reset rather than a true power-down.

That is the whole difficulty: the vendor procedure needs a state this device has
not been observed in since the brick. Two things are worth noting:

- a key-hold reset leaves the RTC and always-on domains alive, which is precisely
  why it is *not* the same as a power-off;
- the ROCKNIX ABL draws an offline-charging screen. A device sitting on that
  screen is not in Android, and it may well be reachable by the charger-side logic
  the vendor procedure depends on.

So the first sub-goal is not the key, it is **achieving a real off state**:

```
hold Power ~15 s           -> reset (what has been done so far)
hold Power much longer     -> possibly a true power-down
remove the charger         -> no VBUS, so no charging-screen wake
```

## 3. The procedure, as the vendor states it

```
1. power the tablet fully off  (no charger, screen dark, no USB enumeration)
2. hold Volume Up
3. with Volume Up held, connect the USB cable to the computer
4. keep holding until the device appears
5. release
```

Verification: the vendor's own text says the result is a **COM port**. That maps
directly onto this repository's tooling:

```
python scripts/tablet.py status                     # watch for a new node / port
python scripts/tablet.py wait --want com --seconds 60
```

The failure mode the card warns about — "if no COM port, please try again" — is
retry advice, which means the manufacturer expects this to be timing-sensitive and
repeatable rather than a one-shot.

## 4. What this could give, and what it could not

If it works, the device enumerates and — depending on which subsystem answers —
this is the state where a `HELLO` may be present again. That is the whole goal of
the current sessions, and this procedure is attractive because it does **not**
depend on:

- the firmware emitting a HELLO at boot (`docs/34`, `docs/35`);
- a hardware short and an unknown pin-out (`docs/41`, `docs/42` route B);
- a debug policy (`docs/42` route C).

It depends only on the device being genuinely off, which is a state the owner can
produce — unlike the other three routes, which each need something nobody has.

## 5. First attempt: no change at all

Attempted 2026-11-11 12:33–12:37 with `tablet.py watch`, which enumerates
**every** USB node with no VID filter, at 2.8 ms per pass.

```
[  0.011]  baseline: 39 USB nodes
[240.006]  no USB device changed during the window
[240.010]  COM port now: COM10
```

**Interpretation, stated carefully:** the tablet never left the bus during those
four minutes. A cable that is unplugged and re-plugged - which the procedure
requires, since the device must be off and then connected - produces at least one
`- GONE` and one `+ APPEAR`. Neither happened.

So this is a **procedure not executed**, not a procedure that failed. The watcher
was verified independently first (2.8 ms/pass, 36 nodes enumerated, the tablet
among them, diff logic checked), because the alternative reading - a blind
detector - is the exact mistake `docs/32` rule 3 exists to prevent.

**What is needed next:** the tablet actually powered off with the cable out,
Volume Up held, and the cable inserted while holding. The hard part remains
`docs/07` §E2: this device has not been observed in a genuine off state since the
brick, and every cycle so far has been a key-hold reset.

## 6. Honest limits

- **Not tried.** This document records a procedure from the package, nothing more.
- Whether the tablet can reach a true off state at all is unknown; `docs/07` §E2
  says it could not, but that was tested while the device was in its crashdump
  cycle and may have been a reset rather than a power-down.
- The card shows a Micro-USB connector illustration while this tablet is Type-C.
  The illustration is generic artwork in a Lenovo tool that covers many models; it
  does not change the key logic, but it is a reminder that the card is not
  model-specific.
- If the device does enumerate, which PID and whether a HELLO is present must both
  be measured — the card only promises a COM port.

## 7. Where this sits in the ranking

`docs/42` ranks the three known routes by what blocks each. This one changes the
ranking, because its blocker is the cheapest of all four:

| route | blocker | who can clear it |
|---|---|---|
| **vendor: off + VolUp + plug** | **reaching a true off state** | **the owner, now** |
| A: bump 900E→9008 | spent HELLO | needs a real cold boot |
| B: FEDL short | unknown pin-out | needs hardware knowledge |
| C: EUD | no declared enable | likely needs the case |

That makes it the first thing to try.
