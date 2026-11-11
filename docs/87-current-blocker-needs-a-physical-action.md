# Where things stand: the device is wedged and needs a physical action

A single page, written because the situation has been the same for several checks and the
next step is not something I can do.

---

## 1. Current state, verified

```
tablet node : USB\VID_0000&PID_0002\9&1FF60AC4&0&4    Status Error, Code 43
COM ports   : COM1 only (no COM10)
last 100 s  : no USB change at all
```

The node is present and Windows reports it as a failed device: *"Unknown USB device
(device request for descriptor failed)"*. It is not `900E`. It is not `9008`.

## 2. What this state is

`docs\07` §D3 records exactly this node and its cause: **replugging the cable while the PBL
is mid-negotiation wedges it.** The device is on the bus but will not answer a descriptor
request, and no host-side action changes that - `pnputil /restart-device` needs
administrator rights and would only re-enumerate, not un-wedge the boot ROM.

Recovery is physical, and it is the same action in both documented cases: **force a real
power-down**.

## 3. What has to happen, and in what order

```
1. unplug the USB cable
2. hold Power 20-30 s, until the screen is dark and nothing returns
3. wait ~5 s
4. plug the cable back in, touching NO keys
```

**Step 4 is not just recovery - it is the control run of the A/B experiment.** If the device
comes back as `900E` with no keys touched, then the `VID_0000&PID_0002` from the earlier
attempt was a replug artefact rather than something the volume keys caused. If it comes back
wedged again with no keys, that is a different and more serious finding.

If 30 s does not work, the escalation is a **long discharge** (30-60 minutes with no power
at all). A key-hold reset leaves the RTC and always-on domains alive; only a real discharge
clears them. That is also the only way to reset the state discussed in `docs\59` §4a.

## 4. Everything is prepared for the moment it comes back

No further work is needed before the device responds. The harness is written and tested:

| tool | purpose | state |
|---|---|---|
| `scripts/tablet.py status` | what is on the bus right now | tested |
| `scripts/tablet.py selftest` | full chain check | tested |
| `scripts/tablet.py read` | HELLO -> MEMORY_DEBUG -> read a region | needs a HELLO |
| `scripts/tablet.py bump` | 900E -> 9008 | needs a HELLO |
| `scripts/tablet.py catch` | hold a handle across a power cycle | tested |
| `scripts/vendor_entry.py` | the manufacturer's procedure, step by step | tested |
| `scripts/ab_test.py` | the volume-key A/B, control vs test | tested |

## 5. Status of the goal

`HELLO ver=3 mode=0` from PBL: **not obtained.**

What the session established, in one paragraph: the hardware is not faulty; XBL runs to
completion and loads APPSBL; the download path exists and was taken once on this device; a
single counter (`dload_entry_count`) and a single cookie bit (bit 12 of `0x1FD9000`) gate it,
and neither is settable by any readable code or from the host; an external log proves the
programmer and Firehose work on this exact model with this exact melf; and a sibling Lenovo
tablet in the same 900E dead-end was recovered by test points with the battery disconnected.

**The remaining blocker is access to 9008, and every route to it now needs a physical
action rather than more analysis.**

## 6. What I cannot do

I cannot press the power button, unplug the cable, or hold a key. Until that happens the
device stays where it is, and every host-side check returns the same two lines.

Which is why this document exists instead of another experiment.
