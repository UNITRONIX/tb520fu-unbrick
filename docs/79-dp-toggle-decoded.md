# The D+ toggle decoded: 200 × 1000 microseconds, then a second toggle

`docs/78` found the constant `0xc8 = 200` but could not say what unit it was in, and
measured 200.84 ms in the log against a nominal 200. The function that consumes it is
now read, and it settles both.

---

## 1. The function at `0x148826a0`

```
0x148826a0  stp  x29, x30, [sp, #-0x20]!
0x148826ac  mov  w19, w0            save the argument (200)
0x148826b0  bl   0x14882618         drive D+ to one state
0x148826b4  movz w8, #0x3e8         w8 = 1000
0x148826b8  mul  w0, w19, w8        w0 = 200 * 1000 = 200 000
0x148826bc  bl   0x148829bc         delay(200 000)
0x148826c0  bl   0x14882664         drive D+ to the other state
0x148826c8  movz w0, #0x14          w0 = 20
0x148826d0  b    0x148829bc         delay(20)
```

## 2. The unit

`0x148829bc` is the microsecond delay routine that `docs\18` traced
(`0x14847cd4` divides by 1 000 000). So the argument is **microseconds**, and:

```
200 × 1000 = 200 000 µs = 200 ms
```

**`w8 = 0x3e8 = 1000` is a milliseconds-to-microseconds conversion.** The caller passes
200, meaning 200 ms, and the function multiplies by 1000 internally.

That resolves `docs\78` §3: the constant *is* milliseconds, and the extra 0.84 ms in the
measured gap is the surrounding work - the `delay(10)` before the call, the two register
writes, and the logging after it. The nominal 200 ms and the measured 200.84 ms are the
same event.

## 3. The sequence is a pulse, not a hold

This is the part that matters for the physical attempt:

```
drive D+ to state A
wait 200 ms
drive D+ to state B
wait 20 µs
```

The firmware does not hold the line; it **toggles it** - one state for 200 ms, then the
other, then carries on. `usb_dp_toggled_for_cdp` is an accurate name: the line is
*toggled*.

## 4. What the two sibling functions do

`0x14882664`, called at the end, is visible immediately after the toggle function:

```
0x148826f4  movz w9, #0x1000
0x148826f8  and  w8, w19, #0xff
0x148826fc  movk w9, #0x88e, lsl #16     w9 = 0x088E1000
0x14882700  ubfm w10, w19, #8, #15
0x14882704  ubfm w11, w19, #16, #23
0x14882708  strh w8,  [x9, #0x0]         write byte 0
0x1488270c  lsr  w8, w19, #24
0x14882710  strh w10, [x9, #0x4]         write byte 1
0x14882714  strh w11, [x9, #0x8]         write byte 2
0x14882718  strh w8,  [x9, #0xc]         write byte 3
```

That is **writing a 32-bit value into four halfwords at `0x088E1000`**, eight bytes
apart. A spread-out store of one word across a register block - the shape of a
"set this bit in this port" helper on a bus with 16-bit lanes.

So the toggle machinery writes to `0x088E1000`, while the *check* reads `0x088E2000`
(`docs\41`). Two different addresses in the same PHY block: one is the control, the other
the status.

## 5. What this changes for the physical attempt

`docs\77` said the firmware "exercises D+ for ~200 ms". It is more precise than that:

```
firmware drives D+ to state A and holds it exactly 200 ms, then flips it to state B
```

**A short applied externally competes with an active driver for 200 ms, and then the
driver flips.** Whether an external low can be observed at all depends on:

- which of the two states the short corresponds to;
- whether the external impedance beats the SoC's drive at that moment;
- and what the *check* at `0x088E2000` actually samples - the driver state, or a
  separate detect comparator.

None of that is answerable from the firmware; it is a hardware question.

## 6. Honest status

The D+ path is now decoded from the constant to the delay unit to the register writes.
That is the most complete picture of any mechanism in this project.

It has not moved the goal. `HELLO ver=3 mode=0` remains unobtained, and the remaining
question - whether a physical short can beat the driver - cannot be settled by reading
anything further.

What it does is replace "hold D+ low and hope" with a specific picture: a 200 ms driven
window, a flip, and a status register that reads differently from the control register.
If a physical attempt is made, this is what is happening underneath it.
