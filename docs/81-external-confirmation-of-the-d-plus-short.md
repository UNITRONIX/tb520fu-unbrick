# External confirmation: the D+ short works only if the bootloader supports it — and this one does

The offline analysis in this repository reached the D+ short by reading firmware. External
sources describe the same technique from the field, and the two agree on the point that
matters most.

---

    10|## 1. What the field sources say

The standard "EDL cable" / "deep flash cable" method:

> To trigger mode 9008, you need to momentarily (for 3-5 seconds) short the Data+ (green)
> line to Ground (black) when connecting the cable to a computer.

> Power off the device completely. Plug the cable into the device. Short (twist) the green
> and black wires. Plug the USB connector into the computer port. Wait for 5 seconds and
> then un-short (separate) the wires.

Source: skesov.com, and the same procedure appears in a no-soldering variant on
groups.google.com (bananahackers).

And the crucial caveat, from an XDA thread about recovering an SM8250 device:

> An EDL cable (grounding USB2 D+) will only work **if they put a test for that in the abl
> and the abl is working**.

## 2. Why that caveat is the important part

That sentence is the field version of what this repository established by disassembly:

| claim | field source | this repository |
|---|---|---|
| the short works only if firmware tests D+ | XDA, quoted above | `boot_fedl_check` reads D+ (`docs\41`) |
| the test must run for the short to be seen | implied by "3-5 seconds" | ~200 ms driven window (`docs\77`, `docs\79`) |
| verification is `05c6:9008` | skesov, droidwin | `tablet.py status` reports `PID_9008` |

**This device passes the caveat.** XBL contains a complete D+ test
(`qusb_dci_dp_gnd_check`, `docs\18`) and a function that reacts to it, and the boot log
shows the D+ line being actively driven for 200 ms on every boot (`docs\77`).

So the method is applicable **in principle** to this tablet. What is missing is not the
firmware support - it is the **physical access**.

## 3. The precedent that matters most

A thread on XDA about a Lenovo Tab 4 (`TB-8704F`) describes a device stuck in **exactly
this state**:

> Connect to PC via USB and a new COM-Port pops up "Qualcomm HS-USB Diagnostics 900E"
> However in order to "deep" flash it I would need to enable QDL / EDL mode. But I don't
> know how. I have already tried combinations of volume +/- buttons and powering the device
> on / plug in USB.

and the resolution, in a linked thread:

> I managed to identify the test point on the motherboard. This allows the tablet to switch
> from Qualcomm HS-USB Diagnostics 900E driver mode to Qualcomm HS-USB QDLoader 9008 mode.

**Same symptom, same vendor, same resolution: a test point on the board.** That is the
closest documented precedent to this unit's situation, and it confirms that the state is
recoverable rather than terminal.

## 4. Two warnings worth recording

From the SM8250 thread, in capitals, by someone who knows the hardware:

> **NEVER** connect wires from a USB cable to points on the main board. Wires in USB can
> carry 3.3V to 5V. 90% of the points on the main board are designed for less than 1.8V.

> USB is USB. EDL test points are EDL test points. NEVER the twain shall meet.

So the two techniques are distinct:

| technique | what it touches | risk |
|---|---|---|
| **EDL cable** | shorts D+ to GND **inside the cable** | low - the connector is designed for it |
| **test point** | a pad **on the motherboard** | high - wrong pad or wrong voltage can destroy the board |

The cable method never connects a USB wire to the board. The test-point method requires a
multimeter first: **measure voltage, and only if it reads near zero use diode mode**.

## 5. What this changes for the goal

Nothing about the blocker, but everything about how to think about it:

- **the D+ short is the right technique for this device**, because the firmware tests for
  it - confirmed from both directions now;
- **it can be done at the connector** (low risk, no disassembly) if the short can be applied
  to D+ within the cable or at the plug;
- **it can be done at a test point** (higher risk, needs the case open) as the documented
  Lenovo precedent shows;
- and **one field report cautions that newer Qualcomm devices may require authorisation to
  *flash*** even after reaching 9008 - which does not affect this goal, since the goal is
  the `HELLO` itself, not a write.

## 6. Honest limits of these sources

- None of them covers the `TB520FU` specifically. No verified test-point image for this
  model was found.
- The "3-5 seconds" guidance conflicts with `docs\77`'s measured 200 ms driven window.
  Both can be true: the short must be present when the firmware looks, and holding it
  longer is harmless. **Hold it through the whole boot**, as `docs\41` already says.
- A field report in the same thread ends in failure - "what could have been accomplished
  here ended in failure with the device in the same state" - so this is not a guaranteed
  path even with the right technique.
