# The dump contains the whole failure story — two boot logs, and DDR recovery between them

`docs/56` found the XBL log at `0x81CE0000`. There is a **second** one at
`0x81A00000`, from an earlier boot, and comparing them shows the device recovering
from a DDR failure by warm-resetting itself.

This is the most informative thing found in the session, and it comes from a file
that has been on disk all along.

---

    10|## 1. Two logs, two different boots

```
0x81A00000   "Format: Log Type ..."  210 lines   Reset Type: Warm Reset
0x81CE4000   "Format: Log Type ..."  296 lines   Reset Type: Shutdown
```

Both are complete XBL logs with `SBL1, Start` and `SBL1, End`. They are separate
boots - the reset type alone proves it, and the timestamps differ throughout.

## 2. The older boot went through DDR recovery

The sequence at the point where the two logs diverge is unambiguous:

```
B - 819138 - sbl1_ddr_init, Start
B - 819199 - PASS1 Cookie =  0xcafe1111
B - 819199 - HAL_DDR_SDI_Recover() start:  DBG PDC Tr = 0x1, First Pass expire = 0x0
B - 819199 - SHRM run state = 0x10
B - 819321 - HAL_DDR_SDI_Recover() end : DBG PDC Tr = 0x1, First Pass expire = 0x0
B - 819321 - SHRM run state = 0x10
B - 819352 - ddr_init status = 0  DDR recover normal pass2
D -       214 - sbl1_ddr_init, Delta
B - 820175 - do_ddr_training, Start
D -         0 - do_ddr_training, Delta          <- ZERO time
```

and, immediately before that, three stacked warm resets:

```
B - 298534 - PM: Reset by PSHOLD
B - 298534 - PM: Reset Type: Warm Reset
B - 298534 - PM: Warm reset count:0x3
B - 298564 - ... Warm reset count:0x2
B - 298564 - ... Warm reset count:0x1
```

**Reading it:** the device failed DDR initialisation on a pass, was warm-reset by
PSHOLD, retried, and on the retry `HAL_DDR_SDI_Recover` succeeded and reported
`ddr_init status = 0  DDR recover normal pass2`.

`0xcafe1111` is a magic cookie marking "pass 1", not an error code. The recovery
path uses it to know which pass it is on.

## 3. And on that boot, training did nothing

```
B - 820175 - do_ddr_training, Start
D -         0 - do_ddr_training, Delta
```

**Zero microseconds.** Compare the newer boot, where the same stage took 33 885 µs
and did real work:

```
B - 742431 - do_ddr_training, Start
B - 766617 - DDR: Start of DDR Training Restore
B - 776194 - Returning from DDR_FW_Restore
B - 776225 - Max enabled DDR Freq = 4224 MHz
B - 776225 - DDR: End of DDR Training Restore
D - 33885 - do_ddr_training, Delta
```

So on the older boot training was **skipped entirely** while reporting success,
and on the newer boot it ran and restored a saved training image at 4224 MHz.

## 4. What this means

Three statements, all measured:

1. **This device has failed DDR initialisation before, and recovered.** The
   warm-reset ladder (`count 0x3, 0x2, 0x1`) plus `HAL_DDR_SDI_Recover` passing on
   pass 2 is the firmware's own recovery mechanism, and it reported `status = 0`.
2. **`do_ddr_training` can return in 0 µs.** A stage that is supposed to take
   ~34 ms reported completion instantly. That is the same "silent early success"
   shape `docs/20` found in the programmer's entry stub - and it means a zero-time
   stage is not proof that the stage did its job.
3. **The two logs differ in how DDR came up**: one skipped training, the other
   restored a saved image. So DDR bring-up on this unit is **not** deterministic
   across boots, contradicting the "fully deterministic" conclusion of `docs/21`.

That last point matters for the goal: if DDR init can take different paths on
different boots, then the programmer's failure may also depend on which path is
taken - which would explain why the same melf behaves identically from outside
while the state underneath varies.

## 5. The battery is a live variable, not a historical note

Both logs, from different boots:

```
older:  UFS Gear 1 due to low battery   VBAT: 3589mV
newer:  UFS Gear 1 due to low battery   VBAT: 3588mV
```

`docs/07` §E1 recorded a 9-hour charge and a clean control run, concluding low
battery explained instability but not the missing Firehose. These logs show the
battery **is still low**, four days and many cycles later, and UFS is still running
at Gear 1 because of it.

Whether that matters for the programmer is unproven - but it is a measured
condition that can be changed, unlike every other blocker in this session.

## 6. What to do with this

In priority order, all offline:

1. **read the rest of both logs line by line**, especially the ABL region after
   `SBL1, End` - the logs stop at SBL1 but the surrounding memory may hold more;
2. **diff the two logs completely** rather than by keyword, to find every stage
   whose timing or path differs;
3. **charge the battery** before any further attempt, since `UFS Gear 1 due to low
   battery` is a measured degradation that costs nothing to remove.

Point 3 is the only action in this whole session that addresses a confirmed,
measured problem with a zero-risk remedy.
