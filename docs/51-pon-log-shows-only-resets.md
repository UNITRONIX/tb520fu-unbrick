# The PON log says the tablet only ever resets — it has never been seen to power off

`docs/44` closed the PMIC-dump avenue and concluded that the question "is a true
off state reachable" could only be answered by observation. Three independent
`PMON_HIS` samples were already on disk and were never decoded. They answer it.

---

    10|## 1. The format

```
0x00  "PLOG"            magic
0x04  u32 = 1           a count or version
0x08  records:  (u8 type, u8 len, u8 data[len])  ...
      terminated by type=0 len=0
```

Record types present in the sample:

```
0x03 len 14   0x04 len 6   0x07 len 8    0x00 len 1
0x06 len 0    0x84 len 3   0x01 len 8    0x01 len 223
```

The large `type=0x01 len=223` record is the interesting one: it is a packed
sequence of the same short patterns, i.e. a **ring of past power events**.

## 2. What the ring contains

Counting the recurring motifs in that payload:

```
07 0f 70 b6 04 07      6 occurrences
70 b6                  6        (cycle marker A)
70 b2                  3        (cycle marker B)
84 03 0e 00 00         7
82 03 0e 00 00         1
01 00 87               1
```

Six occurrences of cycle marker A in a 223-byte ring, plus three of B. The ring is
small and it is **full** - which is itself the first finding: the log has wrapped,
so it holds the most recent events and not the whole history.

## 3. The finding that matters

All three samples - `pon_probe/01_`, `pon_probe/02_` and
`crash_region_probe/sample_0x0081b75058_` - contain **the same record types in the
same order**, differing only in a couple of bytes of the cycle payload:

```
03 0e 00 00 | 07 08 00 03 | 07 0f 70 b6 | 04 07 00 01 | 04 06 00 84 03 0e 00 00
07 08 00 02 | 07 0f 70 b6 | 04 07 00 01 | 04 06 00 84 03 0e 00 00
07 08 00 01 | 07 0f 70 b6 | 04 07 00 01 | 04 06 00 84 03 0e 00 00
01 08 00 00 | 01 0f 70 b2 | 01 05 01 df | 01 0d 00 00 | 05 01 ...
```

The structure is monotonically descending in an index (`00 03`, `00 02`, `00 01`)
followed by a repeat of the same cycle pattern. That is the shape of a **reset
counter winding down and restarting** - the same story `docs/21` told from scalar
registers ("the boot failure is fully deterministic"), now visible as a sequence
rather than a single value.

**And there is no separate event class for a power-down.** Every recorded cycle is
of the same kind. Across three independent captures - taken at different times,
after different numbers of resets - the log never contains a distinct
"powered off" entry.

## 4. What that means for the vendor procedure

`docs/43` records Lenovo's instruction to start from "power off status", and
`docs/07` §E2 recorded that this tablet could not be powered off. The PON log is
consistent with §E2: **in every capture we hold, the device only ever went through
reset cycles.**

That does not prove a power-off is impossible - the log is a small ring and it has
wrapped, so an older power-off would have been overwritten. But it does mean:

- no evidence exists, anywhere in this project, that this tablet has been in a
  genuine off state since the brick;
- the precondition of the vendor procedure has **never** been demonstrated;
- so "the vendor procedure did not work" cannot be claimed - it has never actually
  been run from its stated starting condition.

That is the same distinction `docs/43` §5 draws, and this log is the first evidence
for the earlier half of it.

## 5. What to do with this

The ring is small, so the test is cheap and self-proving:

```
1. run `tablet.py offcheck` and hold Power far past the 15 s reset point
2. if the device stays absent, power it on again
3. read PMON_HIS once more and compare the record sequence
```

A genuine off-and-on should add a cycle whose pattern differs from the reset
cycles already in the ring - specifically, the marker before the descending index
should change. If the ring gains only another identical cycle, the device was
reset again, whatever the screen did.

**This turns the vendor procedure's precondition into a measured, checkable
state**, which is what `docs/43` needed and did not have.
