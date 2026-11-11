# The battery-disconnect procedure: the one step this project never performed

A Lenovo sibling with the identical symptom was recovered, and the decisive difference from
everything tried here is a single step: **the battery was disconnected first.**

Source: XDA thread *[TB128FU] Test points for recovering from Qualcomm Crashdump Mode*:

> I got my TB128FU tablet stuck in Qualcomm Crashdump Mode. I couldn't boot into Android,
> fastboot or EDL. **I couldn't power off the device.** Windows Device Manager confirmed I
> was in Qualcomm 900E diagnostics mode.
>
> 1. open up tablet. Be careful, there is a cable connecting the display and PCB
> 2. **disconnect the battery**
> 3. while shorting the testpoints (I used tweezers), insert a USB cable that's already
>    connected to a PC
> 4. you should now be in EDL mode (Qualcomm 9008 mode)

---

## 1. Why this matters more than anything else found today

`docs\07` §E2 recorded, early in this project, that the tablet **cannot be powered off** -
power always returns to logo, then crashdump. Every attempt since has been a **key-hold
reset**, not a power-down.

A key-hold reset leaves the **RTC and always-on domains alive**. That has consequences this
repository has already documented without connecting them:

| consequence | document |
|---|---|
| the `dload_entry_count` counter is preserved across a key-hold reset | `docs\59` §4a |
| the TCSR cookie at `0xFD9000` survives, because it is always-on | `docs\68` §4 |
| the EUD flag at `0x088E2000` is in an always-on block | `docs\74`, `docs\80` |
| no genuine off state has ever been observed on this unit | `docs\51` |

**All four of those problems are cleared by one action: removing power from the
always-on domain.**

The sibling's procedure does exactly that, and it worked.

## 2. Why it was never done here

`docs\07` §G lists "disassembling the tablet / test point" as *not tried*, with the reason
"requires opening the case; warranty already at risk; **the owner declined**".

That is a decision, not a technical obstacle - and the sibling case is direct evidence that
the decision is the difference between a dead tablet and a working one. It is recorded here
so the trade-off is visible rather than buried:

| keep the case closed | open the case |
|---|---|
| device stays in 900E, silent | battery disconnect + test point short |
| no route to 9008 (all three register routes are closed: `docs\70`, `71`, `80`) | the documented path for this symptom |
| no flash, no repair | Firehose confirmed working on this model once 9008 is reached |

## 3. The procedure, as documented on the sibling

```
1. open the back cover
   - note: there is a ribbon cable between the display and the main board
2. disconnect the battery connector
3. short the test points, holding the short
4. with the short held, connect a USB cable that is already plugged into the PC
5. the device should enumerate as Qualcomm HS-USB QDLoader 9008
6. flash, then reconnect the battery and reassemble
```

Steps 3 and 4 are the ones with model-specific unknowns: **which pads to short.** The sibling
thread has photographs for the TB128FU; no equivalent exists for the TB520FU in anything we
hold, and the searches done this session found none.

## 4. Two techniques, and the difference matters

The XDA hardware thread is emphatic about this, in capitals:

> **USB is USB. EDL test points are EDL test points. NEVER the twain shall meet.**

| technique | what is shorted | risk |
|---|---|---|
| **EDL / deep-flash cable** | D+ to GND **inside the cable** | low - the connector is designed for it |
| **test point on the board** | two pads **on the PCB** | higher - wrong pad or wrong rail can damage the board |

A third variant is possible for this device specifically and is **not** the same as the
dangerous one: the FEDL path in this tablet's firmware (`docs\41`) tests the **D+ line at the
USB PHY**, not a motherboard pad. So a short applied **to the connector's D+ contact** is a
firmware-supported signal, not a random pad. That is the low-risk version, and it needs no
disassembly - but it does need to be applied while the device powers up (see `docs\79`: the
firmware drives D+ for 200 ms and then flips it).

## 5. What to do first if the case is to stay closed

One thing, and it costs nothing:

```
hold Power 20-30 s, unplug everything, leave it 30-60 minutes unpowered
```

A long discharge is a **weaker version** of disconnecting the battery. It may not fully clear
the always-on domain, but it is the only step available without opening anything, and
`docs\51` showed the PON log can verify whether a genuine off state was reached.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

The device is currently wedged (`VID_0000&PID_0002`, Code 43, `docs\87`) and needs a
power-down before anything else can be attempted.

This document exists because the session's findings converge on one point: **the three
register-level routes to 9008 are closed by design, an external log proves 9008 works on this
model, and the documented recovery for this exact symptom begins with disconnecting the
battery.** Every remaining question is about physical access, not about the firmware.
