# 5 h 46 min unplugged changed nothing - because the battery was still connected

A negative result from a real experiment, and it closes a claim that `docs/107` and
`docs/108` both leaned on.

---

## 1. What happened

```
14:41:31   tablet wedged, arrival timestamp (Port_#0004.Hub_#0004)
14:41-20:27  ABSENT from USB - 5 h 46 min, nothing plugged in
20:27:48   back, on a DIFFERENT socket (Port_#0002, root hub 7&14C6E8AD)
```

State on return, measured:

```
USB\VID_0000&PID_0002\8&1B878445&0&2     null descriptor, Code 43
EnumerationRetryCount   4                 (the full budget, spent again)
no VID_05C6 node, no COM port
```

**5 h 46 min with no cable is 11x the 30 minutes `docs/87` recommends, and it made no
difference at all.**

## 2. Why that is the expected result, and what it corrects

`docs/107` said the discharge had never been performed and that it clears the three
always-on blockers. That was half right and half wrong.

**Right:** no *key-hold reset* clears them, and every previous cycle was one.

**Wrong:** unplugging the USB cable is not a discharge. The tablet has an internal
battery (`L20D2P33`, 10200 mAh, `docs/90`). With the battery connected, the always-on
domain is powered whether or not a cable is attached - so "leave it unplugged for 30-60
minutes" cannot clear anything. It only proves the USB path is not involved, which was
never in doubt.

The distinction is the same one `docs/88` already drew and this session then lost:
*disconnecting the battery* is the real action; a long unplug is explicitly "a **weaker**
version" that "may not fully clear the always-on domain". The measurement now says the
weaker version does **nothing measurable** - not "may not".

So the corrected statement of the experiment is:

```
NOT ENOUGH:  unplug the cable, wait 30-60 min
REQUIRED:    disconnect the battery connector (or wait for it to drain)
```

## 3. Corollary: the retry budget is spent per plug, and it is not the blocker

`EnumerationRetryCount` was 4 before the absence and 4 again after. Windows spent the
whole budget again on the new arrival - which is worth stating plainly, because it means
**the host does try**. The device accepts four descriptor requests and answers all four
with zeros. That is the device's behaviour, not a host that gave up:
`EnumerationFailureCode 0x40010000` is recorded *after* the retries, not instead of them.

Two of the four host-side routes explored earlier (`docs/102`, `docs/103`) were premised on
"Windows stopped asking". It did not; it asks, gets zeros, and gives up. That weakens the
case for `remove-device` + rescan, which is now best described as untested rather than
promising.

## 4. What this costs and what it buys

**Costs:** the cheapest-looking experiment turned out to be a null operation, and the honest
version of it needs the case opened or a very long battery drain.

**Buys:** a measurement nobody had, and a sharpening of the remaining options.

| action | verdict after this measurement |
|---|---|
| unplug the cable, wait | **measured: no effect** (5 h 46 min) |
| key-hold reset | known: preserves the always-on domain |
| disconnect the battery (case open) | the only remaining way to clear it - `docs/88`, `docs/90` |
| USB-only routes (host side) | closed or untested, and no longer explained by "host gave up" |

## 5. Where the goal stands

`HELLO ver=3 mode=0`: **not obtained.**

Route (a), the bump, needs a fresh `900E` HELLO; the device returns to `VID_0000` on every
plug, so no HELLO is offered.

Route (b), the D+ short, does **not** depend on any of the persistent state `docs/107`
worried about - `docs/109` established that `boot_fedl_check` reads a latch at ~1036 ms
after power-on, and `docs/41`/`docs/39` that the latch is set by the D+ condition during PHY
initialisation. It is therefore the route that is *not* blocked by the battery problem, and
the measurement above raises its rank rather than lowering it.

**The next attempt should be route (b)**, with the short applied before power-on and the
result then checked in the boot log via `fedl_latch.py` - which distinguishes "short not
seen" from "short seen but EDL blocked".
