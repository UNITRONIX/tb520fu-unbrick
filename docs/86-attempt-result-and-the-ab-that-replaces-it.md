# 2026-11-11 13:00 attempt: result, method error, and the A/B that replaces it

A record of the both-volume-keys attempt, what it did and did not show, and what was
built in response.

---

## 1. What was attempted

The one entry method this repository had never tried (`docs\84`): **Volume Up together
with Volume Down**, held while inserting the cable, from a powered-off state.

Rationale: the PMIC has a distinct PON reason code for both keys (`PON_KPDPWR_RESIN = 2`),
and Volume Down is a PON input that needs no driver - unlike Volume Up alone, which needs
PM8550 gpio6 and never loads on this tablet (`docs\47`).

## 2. What happened

```
[ 32.619]  - GONE    USB\VID_05C6&PID_900E\B6F2DE0A     cable unplugged
[198.717]  + APPEAR  USB\VID_0000&PID_0002\9&1FF60AC4&0&4
```

The device returned as **`VID_0000&PID_0002`**, not `900E`. OS verdict:

```
Status      : Error
Problem     : CM_PROB_FAILED_POST_START (Code 43)
Description : Unknown USB device (device descriptor request failed)
```

and it stayed in that state - **90 seconds of continuous monitoring produced no change**,
no COM port, no `VID_05C6` node.

## 3. Why the result cannot be interpreted

**Two variables changed in one action: the keys were held *and* the cable was moved.**

`docs\07` §D3 attributes exactly this node to replugging the cable mid-negotiation. In
every previous replug during this session the device returned as `900E`, which argues the
keys mattered. But "argues" is not "shows", and the observation cannot distinguish the two
explanations.

**That is a method error, and it is mine.** The correct design was an A/B with the keys as
the only difference. Recording it here rather than reporting the outcome as a finding.

## 4. What was built in response: `scripts/ab_test.py`

```
python scripts/ab_test.py --run control    # unplug, power down, insert cable, NO keys
python scripts/ab_test.py --run test       # unplug, power down, insert cable, BOTH keys
python scripts/ab_test.py --compare        # side-by-side verdict
```

Each run records: state before, whether the device left the bus, for how long, which nodes
appeared, the settled verdict (`absent` / `crashdump-900E` / `EDL-9008` /
`wedged-0000:0002`), and what the port reports. `--compare` prints the conclusion
mechanically, including the one outcome that matters:

| control | test | conclusion |
|---|---|---|
| `900E` | `wedged` | **the keys ARE read** - PON input is live, so the next step is a combination that completes rather than wedges |
| `900E` | `900E` | the keys do nothing; the earlier result was a replug artefact |
| `wedged` | `wedged` | same |
| anything | `EDL-9008` | **goal achieved** |

No VID filter anywhere in it, because a wedged node has no vendor id - which is precisely
why a filtered watcher would have missed the only interesting observation of the day.

## 5. State at the time of writing

```
tablet nodes : USB\VID_0000&PID_0002  (Error, Code 43)
COM ports    : COM1 only
90 s monitor : no change
```

The device is wedged and will not recover without a physical reset. Recommended, and not
yet performed as of this note:

```
1. unplug the USB cable
2. hold Power 20-30 s
3. wait 5 s
4. plug the cable back in, touching no keys   <- this is also the A/B control
```

If 30 s is not enough, the next escalation is a long discharge (30-60 min unpowered),
which is the only thing that clears the always-on domain a key-hold reset leaves alive.

## 6. Status of the goal

`HELLO ver=3 mode=0`: **not obtained.** The device did not reach `9008`.

Two things are true at once and should not be confused:

- **the attempt produced no usable result** about the keys;
- **the attempt produced the first non-`900E` enumeration of the entire session**, which is
  worth following up with the A/B rather than dismissing.

Whether that leads anywhere is unknown. What is known is that the next data point must come
from the control run, and the control run needs the device to be out of the wedged state
first.
