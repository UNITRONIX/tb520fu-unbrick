# Result: both volume keys produce a different USB state than 900E — first deviation all session

Attempted 2026-11-11 13:00. The procedure:

```
1. unplug the cable      -> device left the bus at t=32.6 s
2. power down
3. hold Volume Up AND Volume Down
4. insert the cable while holding  -> node appeared at t=198.7 s
5. hold ~10 s
```

---

## 1. What the watcher recorded

```
[  0.010]  baseline: 39 USB nodes
[ 32.619]  - GONE    USB\VID_05C6&PID_900E\B6F2DE0A
[198.717]  + APPEAR  USB\VID_0000&PID_0002\9&1FF60AC4&0&4
```

**The device came back as `VID_0000 PID_0002`, not as `900E`.**

That is the first time in this entire session that the tablet has enumerated as anything
other than `900E`. Every previous power cycle - dozens of them - produced `900E`.

## 2. What the OS reports

```
Status             : Error
FriendlyName       : Unknown USB device (device descriptor request failed)
InstanceId         : USB\VID_0000&PID_0002\9&1FF60AC4&0&4
Problem            : CM_PROB_FAILED_POST_START
ProblemDescription : Windows has stopped this device because it has reported problems.
                     (Code 43)
```

and it **persisted for the full 60 s observation window** - no COM port, no `VID_05C6` node,
no transition to anything else.

## 3. Why this is not simply the known "wedged PBL"

`docs/07` §D3 describes exactly this node and refutes it as a hidden mode:

> refuted: three **different** ports each produced the same failure. A real mode would
> appear on one specific port. `VID_0000` is a Windows placeholder, not a vendor ID assigned
> by the device, and libusb cannot even see such a device.
>
> **Cause:** replugging the cable mid-negotiation wedges PBL.

That explanation is plausible here too - the cable was physically moved. **But there is a
difference worth recording:** in every previous replug during this session, the device
returned as `900E`. This time it returned as a wedged node, **while two keys were held**.

So one of two things is true:

- the keys changed the outcome, and the device is trying to enter a different mode but
  failing to enumerate; or
- the timing of this replug happened to land mid-negotiation, and the keys are irrelevant.

**The data cannot separate them**, because the two were changed at once (keys held *and*
cable moved). That is a design flaw in the attempt, and the next attempt should not repeat
it.

## 4. What the next attempt must do differently

To isolate the variable, the same procedure has to be run **with no keys held**:

```
control:  unplug, power down, insert cable with NO keys  -> expect 900E
test:     unplug, power down, insert cable holding both  -> observe
```

If the control also produces `VID_0000&PID_0002`, the keys did nothing and this result is a
replug artefact. If the control produces `900E` and the test produces the wedged node again,
**the keys are being read** - which would be the first positive signal of the session.

## 5. Current state and recovery

The device is in the wedged node state and is not enumerating. Standard recovery, from
`docs/07` §D3:

```
hold Power ~15 s to force a reset, then let it settle
```

That should bring it back to `900E`.

## 6. Honest status

**Goal not achieved.** `HELLO ver=3 mode=0` was not obtained; the device did not reach
`9008`.

What this attempt produced is a **new observation** (a different enumeration outcome with
the keys held) plus a **method error** (two variables changed at once), both recorded here
so the next attempt is a proper experiment rather than another guess.
