# The 200 ms is a constant in the code, inside the EUD check

`docs/77` measured a 200 ms gap between two log lines and labelled it as a measurement
rather than a decoded constant. The code has now been read with the correct offset, and
the constant is there.

---

    10|## 1. The sequence

At `0x148798b8`, inside the block that tests EUD:

```
0x14879884  tst  w19, #0xff          EUD state from the earlier check
0x14879888  b.ne 0x148797f0          not the expected state -> skip
0x1487988c  movz w0, #0x1
0x14879890  bl   0x14883070
0x14879894  mov  w0, wzr
0x14879898  bl   0x14882cf8
0x1487989c  bl   0x148799ac
0x148798a0  bl   0x14882dcc
0x148798a4  movz w0, #0xa
0x148798a8  bl   0x14882cb0          delay(10)
0x148798ac  bl   0x14882dd4          query something
0x148798b0  tst  w0, #0xff
0x148798b4  b.eq 0x148797f0          no result -> skip
0x148798b8  movz w19, #0xc8          <-- w19 = 200, THE CONSTANT
0x148798bc  mov  w0, w19
0x148798c0  bl   0x148826a0          perform the D+ toggle with 200
0x148798c4  adrp x0, 0x148b3000
0x148798cc  add  x0, x0, #0x493      "usb_dp_toggled_for_cdp"
0x148798d0  bl   0x14882bb0          log it, with w1 = 200
```

So `0xc8 = 200` is **an immediate in the code**, passed both to the toggle routine and
to the log call. It is not an artefact of log timing - the log prints the value that was
used.

## 2. What the surrounding structure says

The block is guarded by:

```
0x14879884  tst  w19, #0xff
0x14879888  b.ne 0x148797f0
```

and `w19` at that point carries the EUD state. So the D+ toggle for CDP runs **only when
the EUD test produced a particular value**.

Then, after the toggle, the code continues to `0x1487950c` - the same function the
forced-EDL path calls on success (`docs\49`).

That gives a reading of the whole area which was not visible before:

```
EUD check  ->  (condition)  ->  D+ toggle for CDP, 200 units  ->  0x1487950c
```

**The D+ toggle is not an unrelated charger handshake.** It sits between the EUD test
and the function that the forced-EDL path also reaches. That is a genuine finding and it
was only visible after the offsets were computed correctly.

## 3. Units

`docs\77` measured the gap between the log lines as 200 842 µs on one boot and 200 843 µs
on the other - i.e. **200.84 ms**, not 200.00 ms.

So `0xc8` is not a count of milliseconds. Two candidates:

- the value is passed to `0x148826a0`, which may interpret it in some internal unit
  (~1.004 ms per step would fit, but that is suspicious);
- the log line prints the *request*, while the measured 200.84 ms includes the
  surrounding calls (`delay(10)` before it, plus the query and the logging itself).

**The second is more likely and is not proven.** What is certain is that the constant is
200 and that the observed interval is 200.84 ms.

## 4. What this changes

`docs\77` said the D+ toggle "may be CDP enumeration that happens to also be visible to
the FEDL check, or the two may be unrelated." **That reservation is now removed**: the
toggle is inside the EUD-conditioned branch of the same code region that leads to
`0x1487950c`, which the forced-EDL path also calls.

So the honest statement is:

> The early-boot path tests EUD, and when that test yields a particular value it performs
**a 200-unit D+ toggle** and then continues into the function that the forced-download
> path shares. The D+ line is exercised by the firmware as part of the entry machinery,
> not incidentally.

## 5. What is still not established

- **What value of `w19` is required.** The `tst #0xff` / `b.ne` pair means "equal to
  zero" or "not equal", but which state of EUD that corresponds to is not decoded.
- **What `0x148826a0` does** with the 200. Nothing of that function has been read.
- **Whether a physical short can alter the outcome.** The firmware drives the line; an
  external short competes with that driver. Whether it wins depends on drive strength,
  which is a hardware question no file answers.

## 6. Why this was missable, and how it was caught

Two earlier attempts at this address used `offset = VA − 0x14825000` and landed `0x1000`
bytes short, producing coherent PHY-configuration listings that looked plausible.

The correct formula, used throughout the rest of the project, is
`offset = 0x1000 + (VA − 0x14825000)`. The `+0x1000` is the segment's file offset.

**This is the fifth time in this session that a shifted-but-coherent listing was caught
only by checking it against something already known.** The habit that catches it: before
trusting a listing, confirm the first instruction matches what that address is supposed
to be.
