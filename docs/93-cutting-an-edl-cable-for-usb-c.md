# Cutting an EDL cable for a USB-C connector: what is different from micro-USB

The D+ short is supported by this device's firmware (`docs\41`: `boot_fedl_check` tests it),
and it is the only entry route that does not need a locked register. This document covers the
one thing that makes it harder on USB-C than on micro-USB, so the attempt is not wasted.

---

## 1. The field procedure, for micro-USB

From the sources in `docs\81`:

```
1. strip the cable insulation ~15 cm from the connector
2. identify D+ (green) and GND (black)
3. short them together
4. plug the device end in, then the PC end, while holding the short
5. hold ~5 s, release
6. verify 05C6:9008
```

On a **micro-USB** cable this is reliable because the cable has exactly one D+ wire.

## 2. Why USB-C is different

A USB-C receptacle has **two** D+ contacts - `A6` and `B6` - and **two** D- contacts - `A7`
and `B7`. Which pair is live depends on **plug orientation**:

```
plug one way up  -> the cable's D+ lands on A6 (receptacle)
plug flipped     -> the cable's D+ lands on B6
```

Per the USB-C specification (ST AN4871, quoted in `docs\81`), a **plug** carries only one
USB 2.0 pair; the receptacle shorts A6/B6 and A7/B7 on the board to make both orientations
work.

**Consequence for a cable mod:** the cable has one D+ wire, but it only reaches the device's
D+ if the plug is inserted the right way up. **So the cable must be tried in BOTH
orientations** - that is the step most people miss, and it is the most likely reason a
Type-C EDL cable "works once and then stops".

## 3. Which wires to cut, and how to identify them

Typical USB-C cable internals, from the field guides:

| wire | colour | identification |
|---|---|---|
| GND | black | no fabric mixed with strands |
| D+ | **green** | silky fabric mixed in |
| D- | white | silky fabric mixed in |
| VBUS | red | no fabric |

**Do not cut or short the red wire.** Shorting VBUS to GND can damage the host port or the
tablet's charging circuit - both field sources warn about this explicitly.

## 4. The procedure adapted for this tablet

```
1.  remove the hub: plug directly into a rear USB 2.0 port (docs/91)
2.  strip the cable ~15 cm from the USB-C end, expose green and black
3.  unplug the tablet, hold Power 20-30 s until the screen is dark
4.  twist green and black together and HOLD them
5.  plug the USB-C end into the tablet (orientation A)
6.  plug the A end into the PC
7.  hold the short for 5 s, then release
8.  check: python scripts/tablet.py status
```

If step 8 shows nothing, **repeat steps 3-8 with the plug flipped** - that is not a
formality, it is the physics described in §2.

## 5. What to expect

| outcome | meaning |
|---|---|
| `PID_9008` | **the goal's state** - EDL reached; run `tablet.py selftest` to read the HELLO |
| `PID_900E` | the short was not seen; try the other orientation, then a longer hold |
| `VID_0000&PID_0002` | the wedge again - power down and retry |
| nothing at all | the short may be on the wrong pair; verify with a multimeter that green really is D+ |

## 6. The firmware detail that makes this plausible

`docs\79` decoded the toggle:

```
drive D+ to state A  ->  delay 200 ms  ->  drive D+ to state B  ->  delay 20 us
```

The firmware **actively drives D+ and then flips it**. An external short competes with that
driver. This is why the hold must span the whole boot rather than a precise instant - but it
also means the external short has to win against an active driver, which is not guaranteed.

**That is the honest uncertainty.** It is also why this is worth trying before opening the
case: if it works, no disassembly is needed; if it does not, that is evidence pointing at the
test-point route instead.

## 7. Safety, from the hardware thread in `docs\81`

> **NEVER** connect wires from a USB cable to points on the main board.

This procedure touches **only the cable**, never the board. That is the distinction that makes
it low-risk. If the attempt moves to board test points, the method changes completely and
requires measuring voltage first.
