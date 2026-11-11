# The D+ short attempt of 20:27: the PHY trained, the descriptor was zeros

The first real attempt at route (b) on this unit, and what it measured.

---

## 1. What was done

Owner's account, verbatim in substance: the tablet was charged for a long time, then the
EDL cable was plugged in **with the short held**, following the procedure for a powered-off
device.

Timeline from the host side:

```
14:41:31   previous wedge, node on Port_#0004 (through a hub)
14:41-20:27  absent from USB - 5 h 46 min, nothing connected
20:27:48   arrival on Port_#0002 (root hub, different socket)
```

## 2. What the port said, and why the combination matters

```
ConnectionStatus   2    DeviceEnumerated
Speed              2    FullSpeed (12 Mbit)
DeviceAddress      0
NumberOfOpenPipes  0
DeviceDescriptor   length 0, vid 0x0000, pid 0x0000
EnumerationRetryCount 4
```

Read one field at a time this looks like every previous wedge. Read together it does not:

- **`Speed = FullSpeed` is only assigned after the device's PHY trains.** The hub does not
  know a speed for a device that never answered. So the tablet's USB PHY is alive, driving
  the line, and completed the chirp/handshake.
- **`DeviceDescriptor length = 0`** means the descriptor exchange that followed returned
  nothing - hence `DEVICE_DESCRIPTOR_FAILURE` and the null HWID.
- **`DeviceAddress = 0` with `DeviceEnumerated`** is the contradiction that names the state:
  the hub believes enumeration finished, and the address was never assigned.

So the device is *further along* than "no USB at all" and *exactly* at the point where Sahara
has not yet answered. Whether the D+ short latched is a separate question, and it is the one
that matters.

## 3. What this does not tell us, and the one measurement that would

The short could have failed for two very different reasons:

| possibility | evidence that would distinguish it |
|---|---|
| the short was never seen (wrong pad, wrong pair, charge-only cable) | `Boot Config @ 0x221C8600` bits 1-5 still `0` |
| the short was seen, and EDL was blocked downstream | `Boot Config @ 0x221C8600` bits 1-5 `== 6` |

`docs/109` established both the condition and its position on the boot timeline
(`boot_fedl_check` at ~1036 ms, after the firmware's own D+ toggle at ~800 ms). The value is
printed in every XBL boot log, so a **fresh capture after this attempt** answers it directly:

```
python scripts/fedl_latch.py --dump <new capture>
```

There is no capture from this attempt yet. Reading the latch requires a crash-dump session,
and the device is currently wedged - so this remains the open question, not a closed one.

## 4. What the reading does establish

`docs/110` measured that 5 h 46 min unplugged changes nothing, because the battery keeps the
always-on domain alive. This attempt is consistent: the tablet came up in the same wedged
state, which is what a key-hold or connect-at-power-on cycle is expected to produce.

But it also produces the first evidence that **the USB path itself is intact on this unit** -
the PHY trains and the hub sees a real connection. That was assumed before; it is now
measured. It rules out a dead connector, a dead PHY, and a charge-only cable for this cable.

## 5. What to change in the next attempt

Three things, in order of how likely they are to matter:

1. **Apply the short before the cable, not at the cable.** `docs/109` puts the PHY
   configuration at ~600 ms and the latch read at ~1036 ms. The short must be electrically
   present across both, so the order should be: short applied → cable in → power on → hold
   ≥1.5 s. Plugging the cable in *as* the power source starts the 600 ms window immediately.
2. **Try the other plug orientation.** `docs/93` §2: a USB-C plug reaches D+ on one side
   only (A6 or B6), so one orientation can be electrically incapable of the short.
3. **Use the socket whose `9008` identity is bound to `qcwdfser`.** This attempt was on
   `Port_#0002`, whose recorded `9008` identity is libwdi WinUSB (`docs/105`) - so even a
   perfect EDL entry there would have produced no COM port to read. That is not why this
   attempt failed, but it would have masked a success.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

New: the D+ short has been attempted once on this unit and produced `FullSpeed` +
`DeviceEnumerated` + a null descriptor. The USB path is proven alive; whether the short
latched is still unmeasured, and `fedl_latch.py` is the instrument for it.
