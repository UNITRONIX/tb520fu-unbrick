# The forced-EDL path: one 5-second window, and it is reachable two ways

`docs/39`–`docs/42` established the entry *conditions* but left the *timing* of
the window open, and `docs/48` settled that `check_dp_timeout` is a duration with
an action rather than a poll. This document closes the last timing question, from
`0x14879600`, which is the function that actually logs `enter forced EDL`.

---

    10|## 1. The function, in order

```
0x14879600  ldrb w8, [x8]              a configuration byte
0x14879604  cbz  w8, 0x1487961c        not set -> return
0x14879610  bl   0x148796f8            a probe; failure path
0x14879630  ...
0x14879634  cbz  w20, 0x1487964c       mode 0
0x14879638  cmp  w20, #0x2
0x1487963c  b.eq 0x14879668            mode 2
0x14879640  cmp  w20, #0x1
0x14879644  b.ne 0x1487961c            anything else -> return
0x14879648  movz w19, #0x1
0x14879650  bl   0x1488254c            EUD check (bit 0 of 0x088E2000)
0x14879654  tst  w0, #0xff
0x14879658  b.eq 0x14879698            EUD not active -> other path
0x1487965c  mov  w0, wzr
0x14879660  bl   0x1487950c
```

So there are **three modes** (0, 1, 2), and the EUD test only applies to mode 1.
Mode 2 takes a different route entirely:

```
0x14879668  movz w0, #0x7
0x1487966c  bl   0x148639c8            query something with id 7
0x14879678  movn w8, #0x8000, lsl #16  w8 = 0x7FFFFFFF
0x1487967c  cmp  w0, w8
0x14879680  b.eq 0x1487961c            no answer -> give up
0x14879684  adrp x0, 0x148b3000        "enter forced EDL"
0x14879690  bl   0x14882bb0            log it
0x14879694  b    0x148796f0
```

## 2. The fallback path and its window

When EUD is **not** active, `0x14879698` runs the sequence that was read in
`docs/18` but never placed in this context:

```
0x14879698  movz w0, #0x1
0x1487969c  bl   0x14883070
0x148796a0  mov  w0, wzr
0x148796a4  bl   0x14882cf8
0x148796a8  bl   0x148799ac
0x148796ac  bl   0x14882dcc
0x148796b0  movz w0, #0xa
0x148796b4  bl   0x14882cb0            delay(10)
0x148796b8  bl   0x14882dd4
0x148796bc  tst  w0, #0xff
0x148796c0  b.eq 0x14879618            no result -> return
0x148796c4  mov  w0, w19
0x148796c8  mov  w1, w21
0x148796cc  bl   0x14882e78            the D+ poll routine from docs/18
0x148796d0  tst  w0, #0xff
0x148796d4  b.eq 0x1487965c
0x148796d8  adrp x0, 0x148b3000        "enter forced EDL"
0x148796e4  bl   0x14882bb0            log it
0x148796e8  movz w0, #0x1388           w0 = 5000
0x148796ec  bl   0x148829bc            delay(5000)
0x148796f0  movz w19, #0x1
```

`0x1388` is **5000**, and the delay routine was traced to microseconds in
`docs/18` (`0x14847cd4` divides by 1 000 000). So the delay after a successful D+
detection is **5 seconds**, not 50 ms.

## 3. What that corrects

`docs/18` concluded: "the poll runs once, early in USB initialisation, for roughly
50 ms... the short cannot be timed into that window."

The 50 ms figure was the *poll* loop, and it is correct as a description of
`0x14882e78`. What `docs/18` did not see is the surrounding structure:

```
detect D+ condition  ->  "enter forced EDL"  ->  delay(5000)  ->  proceed
```

The 5 s is not a detection window - the detection has already happened by then -
it is a **settle delay before the download continues**. That distinction matters:

| question | answer |
|---|---|
| how long must the short be present? | just long enough for the poll, which runs once |
| is there a 50 ms deadline to hit? | it is one poll pass, but it is **not skipped** on failure — the path retries the whole sequence |
| does anything wait 5 s? | yes, after success, before proceeding |

So the practical instruction is unchanged and now better justified: **apply the
short before power-on and hold it**. There is no window to race; there is a poll
that must find the condition already true, and then a 5 s settle.

## 4. Two ways in, and one does not need the short

The mode-2 branch matters for the goal:

```
mode 2  ->  query(id 7)  ->  if answered  ->  "enter forced EDL"
```

That is an **EUD-driven entry that never calls the D+ poll**. It depends only on
whatever `0x148639c8` with id 7 reports, and on `0x1488254c`'s EUD bit for mode 1.

So the ranking in `docs/42` gains a detail: **route C (EUD) bypasses the short
entirely**, which is why it would be the better route if EUD could be made active.
`docs/42` already recorded that no DTB property enables it.

## 5. Status

Everything above is static reading of the image. **No part of it has been
executed.** The goal - `HELLO ver=3 mode=0` from PBL - remains unmet, and the
verified device state at the time of writing is:

```
PID_900E present, COM10 present, bytes pending 0
```

so route A cannot run, and routes B and C both need a physical action that has not
yet been attempted with the required precondition (cable out, then power, then
key or short).
