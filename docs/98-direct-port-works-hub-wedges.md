# Direct port: 900E enumerates correctly. Hub: wedges. Same device, minutes apart.

A correlation worth recording, with its sample size stated plainly.

---

## 1. The two observations

**13:24 — direct root port**

```
PID_900E  USB\VID_05C6&PID_900E\B6F2DE0A
parent    USB\ROOT_HUB30\7&14c6e8ad&0&0
COM10     present
selftest  enumeration PASS, port PASS, port opens PASS, bytes pending FAIL
```

The device enumerated **normally**, as a Qualcomm diagnostics port, with a working COM port.
No wedge. This was the first direct connection of the entire session.

**13:28 — after being unplugged and reconnected to a hub**

```
USB\VID_0000&PID_0002\9&1FF60AC4&0&4
parent    USB\VID_1A40&PID_0101\8&1B878445&0&4
location  Port_#0004.Hub_#0004
HWID      USB\DEVICE_DESCRIPTOR_FAILURE
```

The same device, four minutes later, on a hub: **wedged**, cannot deliver a descriptor.

## 2. What this suggests, and how strongly

The device enumerated cleanly on the direct port and failed to enumerate on the hub. That is
the first time in this project the two conditions were observed within minutes of each other
on the same hardware, with nothing else deliberately changed.

`docs\07` §D3 attributes `DEVICE_DESCRIPTOR_FAILURE` to *replugging the cable mid-negotiation*,
which is a plausible competing explanation here too - the cable was moved, so the failure
timing is not controlled.

**Sample size: one.** One clean direct enumeration, one wedged hub enumeration. That is enough
to justify a controlled test and not enough to conclude anything.

## 3. The test that would settle it

Same device, alternating, with nothing else changed:

```
1. move the cable from hub to root port     -> record verdict
2. move the cable from root port to hub     -> record verdict
3. repeat once more each way
```

If the verdict follows the **port** (root = `900E`, hub = wedged, every time), the hub is
implicated. If the verdict follows the **number of replugs** regardless of port, it is the
`docs\07` §D3 mechanism and the hub is irrelevant.

`scripts\ab_test.py --run control` records the verdict either way; the port parent is read by
`docs\95` §4's one-liner.

## 4. Why it matters for the goal

If a hub can hold this device in `DEVICE_DESCRIPTOR_FAILURE`, then every negative result taken
through a hub in this session is **confounded** - and that is most of them:

| observation | topology |
|---|---|
| `docs\52` silence at every baud rate | unclear, not recorded |
| `docs\85` both-keys attempt | behind 2-3 hubs |
| `docs\94`, `docs\96` wedged node | behind 1-3 hubs |

None of those results is *wrong*, but none of them was taken on a clean chain. The first
direct-connection measurement (`900E`, normal enumeration) is the only one that was.

## 5. Immediate situation

The device is **wedged on the hub right now**. It needs power removed before anything else:

```
1. unplug the cable
2. hold Power 20-30 s
3. plug back in - and plug into a ROOT port if one is free
```

Then `python scripts\tablet.py selftest` will say whether the direct port gives `900E` again,
which would be the second data point for §2.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.** No `9008`, no fresh HELLO at any point today.

The one genuinely new fact from this window: **the device enumerated normally on a direct
port.** Everything before that was behind hubs. That is worth one controlled test before
concluding anything about the programmer, the DDR, or the hardware.
