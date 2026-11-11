# The tablet is behind a hub, and the hardware ID is `DEVICE_DESCRIPTOR_FAILURE`

Two facts about the current wedged state that were not recorded before, and both matter for
what to try next.

---

## 1. The hardware ID is the one `docs\07` already named

Querying the wedged node's properties:

```
DEVPKEY_Device_HardwareIds   = USB\DEVICE_DESCRIPTOR_FAILURE
DEVPKEY_Device_CompatibleIds = USB\DEVICE_DESCRIPTOR_FAILURE
DEVPKEY_Device_ProblemCode   = 43
DEVPKEY_Device_DriverDesc    = Unknown USB Device (Device Descriptor Request Failed)
```

`USB\DEVICE_DESCRIPTOR_FAILURE` is the exact string `docs\07` §D3 discusses. That section
refutes it as a hidden mode and attributes it to replugging the cable mid-negotiation. So the
current state is the documented one, confirmed at the property level rather than by
appearance only.

## 2. The tablet is connected through a hub

```
DEVPKEY_Device_Parent = USB\VID_1A40&PID_1A40...  (VID_1A40 PID_0101)
```

`VID_1A40` is a generic USB 2.0 hub controller. So the chain is:

```
PC root port  ->  external hub (VID_1A40)  ->  tablet
```

**This was never part of the recorded setup.** `docs\52` recorded the working connection as
`LOCATION=1-4.4`, and `scripts\usb_watch/FastUsbWatch.cs` was written to watch "every USB
device, no VID filter" - but nothing in the repository says whether the successful sessions
went through a hub or straight into the machine.

That matters for three reasons:

1. **A hub changes what "hold the short while inserting the cable" means.** The device
   negotiates with the hub first; the hub then reports to the host. A device that fails
   descriptor negotiation can fail at either stage.
2. **`docs\07` §A5 tested "USB 2.0 port instead of USB 3" and found no change** - but a hub
   is not the same as a different root port, and it was never listed as a variable.
3. **For the FEDL attempt (`docs\41`), the hub is a real risk of introducing its own state.**
   The recommended practice in the field sources (`docs\81`) is a **direct** connection to a
   USB 2.0 port on the host, explicitly to avoid hub behaviour.

## 3. What to do differently

Before the next attempt:

- **connect the tablet directly to a rear USB 2.0 port**, no hub, no extension, no
  front-panel header if it can be avoided;
- confirm the location changes: it should read `Port_#xxxx.Hub_#xxxx` with a *root* hub as
  the parent, not `VID_1A40`;
- then run `scripts\ab_test.py --run control`.

If the wedged state does not reproduce on a direct connection, then the hub was contributing
to it - and that would also change how the earlier `VID_0000&PID_0002` result should be read
(`docs\85`, `docs\86`).

## 4. What this does not claim

- **It does not say the hub caused the wedge.** `docs\07` §D3's explanation (replug during
  negotiation) remains the leading one and is independent of the hub.
- **It does not say earlier sessions used a hub.** The evidence is not recorded either way,
  which is precisely the gap this document closes for future attempts.
- **It does not change the recovery step.** The device still needs power removed; the hub is
  a variable in the *next* attempt, not in the current stuck state.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.** Device wedged, verified at property level as
`USB\DEVICE_DESCRIPTOR_FAILURE`, parented to a generic hub.

One concrete, free change to the setup before the next attempt: **remove the hub from the
chain.** That is now recorded so it is not discovered by accident later.
