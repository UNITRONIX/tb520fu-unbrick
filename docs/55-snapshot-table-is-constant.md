# The snapshot table is constant across boots — it is configuration, not state

`docs/54` proposed the cheap test: read the three-halfword snapshot table from a
second dump and see whether it changes. A second dump was already on disk. The test
is done, and the answer is unambiguous.

---

    10|## 1. The two captures are genuinely independent

```
dump A  com_attempt/DDRCS0_0_first40MB.bin            41 943 040 B
dump B  com_attempt/real_content/DDRCS0_0_first28MB.bin 29 360 128 B
```

Comparing the common 28 MiB at 64-byte granularity:

```
blocks compared   458 752
blocks differing   83 542   (18.2 %)
blocks identical  375 210
4 KiB pages differing: 1 487 of 7 168
```

So these are **two different boots**, not two copies of one capture. The differing
pages (`0x80092000`, `0x800C4000`–`0x800CA000`, ...) are live memory that moved
between sessions.

## 2. The table itself

```
address        dump A    dump B    verdict
0x800DF408     0x80E1    0x80E1    same
0x800DF40A     0x2022    0x2022    same
0x800DF40C     0x0040    0x0040    same
0x800DF410     0x8AA5    0x8AA5    same
```

Every byte identical, while 18 % of the surrounding memory changed.

## 3. What that settles

The test was designed to separate two possibilities:

- **constant** -> configuration or a fixed echo of PHY defaults;
- **changing** -> a capture of the crash condition.

**It is constant.** So the table at `0x800DF408`–`0x800DF414` does **not** record
what the USB PHY looked like at the moment of each crash. It carries the same
values on both boots, which means either it is never written by the path in
`docs/53`, or it is written with values that are always the same on this board.

Consequences, stated plainly:

- **the HWID-like value `0x202280E1` is not evidence about the crash.** Whatever it
  is - and `docs/54` already refused to call it the HWID because the store is 16
  bits - it is the same in both captures, so it cannot distinguish one failure from
  another;
- the "read the device's own record of the PHY state" idea, which was the most
  promising thing found in several hours, **does not pan out**;
- `0x0040` and `0x8AA5` are likewise constants, not observations.

## 4. Why this is worth recording as a result

It was a good hypothesis, it was cheap to test because the data already existed,
and it is now closed with a measurement rather than left as a hope. That is the
standard `docs/07` sets.

It also removes a source of future error: had the table been read in a live session
and its values interpreted as "the state at this crash", the conclusion would have
been drawn from a constant. The constant-ness is only visible by comparing two
boots, which is exactly what was done.

## 5. Where this leaves the goal

Unchanged and re-verified: the device presents as `PID_900E`, `COM10` opens, and no
HELLO appears at any baud rate (`docs/52`). Both routes remain blocked:

- **route A** needs a fresh HELLO, i.e. the firmware stage that emits it must run;
- **route B** needs the D+ latch set before power-on, i.e. a physical short and a
  pin-out that no file we hold describes (`docs/45` §4).

The offline avenue "read the device's own crash record" is now exhausted, because
the record that exists is invariant. The remaining unknowns are physical facts, and
the next action is the vendor procedure run from a verified off state
(`scripts/vendor_entry.py`, `docs/51`).
