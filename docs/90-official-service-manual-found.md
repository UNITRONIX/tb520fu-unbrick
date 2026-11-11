# The official Lenovo service manual for this model, and the disassembly SOP

`docs\88` concluded that the remaining recovery path begins with disconnecting the battery,
and that `docs\07` §G recorded the owner declining to open the case. This document records
what the manufacturer's own service manual says about doing it, so the decision can be made
on facts rather than on "opening the case is risky".

Source: **Lenovo Product Maintenance Manual** (PDF), plus the vrm24 teardown for a sibling
Yoga Pad Pro model and Lenovo's PSREF spec sheet for the battery part number.

---

    10|## 1. The manual exists and covers this machine

It is a Lenovo service document with the standard structure: safety, ESD handling, FRU
replacement, disassembly SOP, explosive view, and part-number ordering. Relevant sections:

```
8.1 Repair Tool
8.2 Common Repair Tips    (with Lenovo's own video links for adhesive work)
8.3 Key Tips
8.4 Disassembly SOP
9.1 Explosive View        (screw locations)
9.2 How to Order PN
```

## 2. What the manual says, verbatim where it matters

**Before opening:**

> Failure to follow the repair instructions or not to use genuine parts or proper tools may
> damage the device or compromise the device's functionality or water resistance.
>
> The tablet components may be damaged by electrostatic discharge (ESD). Always use an ESD
> mat and ground strap when working with internal components.
>
> Turn off the device before repair.
>
> Loose screws, extra screws, or small parts inside the device can cause safety issue. Set
> aside all parts and screws removed during repair.

**The opening procedure:**

> Power off the device, wear SD Bracelet before disassembly.
>
> Apply the suction cup to the front housing at the upper middle location, tablet screen
> facing upward in landscape mode. Then insert a guitar pick between the gap starting from
> the top left as shown in picture, then slide around the edges following the direction of
> the arrows. **Note: The guitar pick should be inserted no deeper than mm.**

**Key tips:**

> 1. The Rear Cover FRU assembly include Battery Adhesive.
> 2. The TPLCM is hook structure, no need adhesive.

And the explosive view notes **six green screws circled in red** as the screw locations to
track.

## 3. What the sibling teardown adds

The vrm24 teardown for a Lenovo Yoga Pad Pro model gives the sequence in steps, which
confirms the manual's outline and adds the parts the manual leaves to photographs:

```
Step 2  open the back cover  - thin plastic tool in the gap between display edge and back
                               cover, release the clips, work along the edges, do not force
Step 3  two screws hold the battery connector - 1.5 mm Phillips / PH #000
Step 4  disconnect the battery connector with a NON-METAL tool
Step 5  screws hold the main PCB - remove brackets
```

**Steps 3 and 4 are the ones that matter here**: the battery connector is held by two screws
and is lifted with a **non-metal** tool. That is exactly the safe procedure for getting the
always-on domain off power.

## 4. The battery, for reference

From Lenovo's PSREF for the Yoga Tab Plus and the parts listing for `TB520FU`:

```
part number : L20D2P33
capacity    : 10 200 mAh
adhesive    : the Rear Cover FRU assembly includes Battery Adhesive
```

So the battery is **adhesively mounted under the rear cover**, which is why the manual
includes a dedicated video: *"How to remove pulling battery adhesive"*
(`osd.lenovo.com/...shareId=57317`).

## 5. What the tool list is

From the manual's repair-tool section and the teardown:

| tool | purpose |
|---|---|
| suction cup | lift the rear cover once clips release |
| guitar pick / thin plastic | release the rear-cover clips, **no deeper than the stated limit** |
| Phillips #000 / 1.5 mm | the two battery-connector screws, and PCB screws |
| non-metal spudger | lift the battery connector |
| ESD mat + wrist strap | required by the manual |

## 6. The honest reading of the trade-off

The manual does not present this as exotic. It is a routine FRU procedure with a documented
tool list, two screws over the battery connector, and an adhesive note. That does not make it
risk-free:

- **water resistance is compromised** once the cover is off (the manual says so explicitly);
- the **display ribbon** runs between the display and the board - the sibling thread warns
  about it by name;
- the guitar pick depth limit exists for a reason, and the manual does not state the number
  in the extracted text.

But "the owner declined" (`docs\07` §G) was a decision made before this manual had been
found, before the sibling precedent was known, and before an external log proved Firehose
works on this exact model. Those three facts change the cost-benefit:

| before today | now |
|---|---|
| opening the case = unknown procedure | **Lenovo's own SOP, with tool list and screw map** |
| no precedent that it helps | **a sibling in the same state was recovered this way** |
| not certain 9008 would even be usable | **a TB520FU log shows Firehose configuring and flashing** |

## 7. Status

`HELLO ver=3 mode=0`: **not obtained.** The device is wedged (`VID_0000&PID_0002`,
`docs\87`) and needs power removed before anything else.

This document does not recommend opening the tablet. It records that the procedure is
documented, the parts are identified, the tool list is short, and the precedent is real - so
that the decision, whatever it is, is made with the manual in hand rather than without it.
