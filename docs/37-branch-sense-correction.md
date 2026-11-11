# Correction: the branch sense at 0x1482eb14 is inverted in `16-firehose-bringup.md`

Static re-reading of `sbl1_ddr_init`, with the decoder verified against the
predicate `docs/16` §5 already documented. The predicate is right. The branch
annotation is not, and that changes what the code actually does on this board.

---

    10|## 1. The instruction sequence, verified

`0x1484396c`, the TCSR predicate, disassembles exactly as `docs/16` §5 says:

```
0x1484396c  movz w8, #0x9000
0x14843970  movk w8, #0x1fd, lsl #16     w8 = 0x1FD9000
0x14843974  ldrh w8, [x8, #0x0]          16-bit read of the TCSR register
0x14843978  tst  w8, #0x30               test bits 4 and 5
0x1484397c  csel-family w0, wzr, wzr, eq  CSINC-style select
0x14843980  ret
```

`CSINC w0, wzr, wzr, EQ` returns `0` when `EQ` holds and `1` otherwise, so:

| TCSR bits `0x30` | `w0` |
|---|---|
| clear | 0 |
| set | 1 |

Caller:

```
0x1482eb0c  bl 0x1484396c
0x1482eb10  tst w0, #0xff
0x1482eb14  b.eq 0x1482eb64        <- taken when w0 == 0
0x1482eb18  mov w22, wzr
0x1482eb1c  b 0x1482ebd4           <- straight to "do_ddr_training, Delta"
```

## 2. What `0x1482eb64` actually contains

```
0x1482eb64  ldr x8, [sp, #0x10]
0x1482eb68  ldr x8, [x8, #0xf0]     vtable slot +0xf0
0x1482eb6c  blr x8
0x1482eb70  cbz w0, 0x1482eb88
0x1482eb74  ...                     vtable slot +0x10 with (2, 1)
0x1482eb88  ldr x8, [x8, #0x90]     vtable slot +0x90
0x1482eb90  blr x8
0x1482eb94  tst w0, #0xff
0x1482eb9c  ...                     vtable slots +0x88, +0x98
0x1482ebb4  mov w22, w0
0x1482ebc0  ...                     vtable slot +0x10 with (2, 0)
0x1482ebd4  "do_ddr_training, Delta"
```

That is four vtable calls plus two status updates - the shape of work, not the
shape of a decision. The other arm, `w0 == 1`, is two instructions and then jumps
straight to the Delta log.

## 3. The correction

`docs/16` §5 annotates the branch as:

```
0x1482eb14  b.eq 0x1482eb64         w0 == 0 -> skip training
```

**Inverted.** `w0 == 0` (TCSR bits `0x30` clear) is the arm that runs the vtable
sequence. `w0 == 1` (bits set) is the arm that skips it. So:

| condition | behaviour |
|---|---|
| TCSR bits `0x30` **clear** | the DDR vtable sequence **runs** |
| TCSR bits `0x30` **set** | it is **skipped**, straight to the Delta log |

The name-level reading - "if the bits are set, skip DDR work in EDL" - is
consistent with this, and it is the reading `docs/16` argues for in the same
section. Only the arrow in the listing is wrong.

This matters because it decides what a device with bits clear is doing when it
goes silent: it is not sitting in a decision, it is inside
`vtable+0xf0 → +0x90 → +0x88 → +0x98`.

## 4. Why it cannot be settled further from the host

`docs/16` §5 already measured that reading TCSR `0x1FD9000` kills a 900E session:

```
case                              pre   test   post  verdict
TCSR 0x1FD9000 (the DDR guard)     ok     NO     NO   killed the session
```

So whether this unit takes the work arm or the skip arm cannot be read. The
inference chain stops here:

```
skip_ddr_init_in_EDL = 0  (declared in the DCB, verified in image[4])
        |
        v
sbl1_ddr_init is called  (docs/16 s4.3, branch direction verified)
        |
        v
do_ddr_training, Start is logged, then the TCSR decision
        |
        X   TCSR 0x1FD9000 unreadable - no 900E session survives it
        |
        v
either the vtable sequence runs (bits clear) or it does not (bits set)
```

## 5. Added finding, and it is the useful one

Since the DDR training record covers all eight 2 GiB windows
(`36-ddr-training-covers-all-windows.md`), and the function is entered with the
"run DDR init" property at 0, the two remaining ways this hangs are narrowed to
the vtable sequence itself:

- a `blr` into a slot that the EDL environment has not populated, which returns
  garbage or branches to nothing;
- a call that waits on hardware - PMIC, UFS link, or an interrupt - that never
  arrives.

Both would end in the same place: `main` returns, the entry stub falls into
`b .`, and the watchdog collects the device ~8 s later. That is exactly what
`20-entry-point-spin.md` and `15-crashdump-memory-access.md` measured. The static
picture and the dynamic evidence now agree, which is the most this can be pushed
without device access.

## 6. Method note

The offset I first used for the predicate (`0x1e96c`) was wrong by exactly
`0x1000`, one segment boundary, and produced a coherent-looking listing of a
different function. Recomputed as `0x1484396c − 0x14825000 + 0x1000 = 0x1f96c`
and it then matched the predicate `docs/16` documents, instruction for
instruction. This is the fourth time in this project that a plausible listing
from the wrong address was caught only by checking it against an independent
statement of what the code should be.
