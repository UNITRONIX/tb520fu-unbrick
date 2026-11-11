# PMIC dump: a header and a scattered record log, not a register block

`scripts/pmic_state_probe/sbl_pmic_dump.bin` — the full 512 KiB region the crash
dump exposes as `sbl_pmic_dump.bin` ("PMIC registers"). `docs/15` §2 lists it as
readable and never analysed it further. This is what is actually in it, and what
is not.

---

    10|## 1. Size versus content

```
file            524 288 B
nonzero bytes     2.7 %
bytes in runs >= 8 B      2 959
nonzero runs >= 8 B         221
```

So 99.4 % of the region is zero. This is **not** a dense register dump; it is a
mostly-empty buffer with a small number of structures scattered through it. The
table entry's description ("PMIC registers") overstates it.

## 2. The header

```
0x00  u32   3
0x04  "RD\0\0" "SBL\0"        two 4-byte tags
0x0c  u32   0x21c50
0x10  0e 02 00 00
0x14  ...
```

`RD` reads as register dump, `SBL` as the producer. The `0x0c` value `0x21c50`
(138 320) is larger than any plausible count of entries that follow, so it is
probably a size or offset rather than a count - not established.

## 3. The entry table at 0x14, read big-endian

The pairs only resolve when read big-endian, and then the indices are a clean
sequence - which is the check that the endianness is right, not a guess:

```
0x14  ...
0x18  idx 0x0001  val 0x4902
0x1c  idx 0x0002  val 0x4502
0x20  idx 0x0003  val 0x4502
0x24  idx 0x0004  val 0x4502
0x28  idx 0x0005  val 0x0000
0x2c  idx 0x0006  val 0x4502
0x30  idx 0x0007  val 0x4702
0x34  idx 0x0008  val 0x4602
0x38  idx 0x0009  val 0x0000
...
0x4c  idx 0x0100  val 0x0000
0x50  idx 0x0101  val 0x0000
...
0x84  idx 0x0000  val 0x0100
0x88  idx 0x2100  val 0x0102
```

Two groups of fourteen: `0x00xx` (14 entries, 8 nonzero) and `0x01xx` (14
entries, all zero). Reading the high byte as a PMIC SID and the low byte as a
register number is consistent with the `0x00xx` / `0x01xx` split.

Interpretation: **14 register values for the primary PMIC and 14 more for a
second SID, of which the second is entirely zero.** Whether the zeros mean "not
populated" or "not readable at the time" is not determined.

## 4. The scattered records

Three near-identical records appear at a fixed stride:

```
0x00ec4   16 01 08 03   11 07 14 4c   ff ff ff fc
0x012d4   16 01 1c 03   11 07 90 41   ff ff ff fc
0x016e4   16 01 08 03   11 07 e4 41   e8 03 ff c5
```

Each begins `16 01`, then a counter that increments by `0x14`, then `03`, then
`11 07`, then a value that changes, then a signed `-4` (or a different value in
the third). A fixed stride with an incrementing index is a **record array**, not a
register snapshot - it reads as a log of events or requests, each 4 words.

Around them:

```
0x00f40   ff ff ff fc  ff ff ff ff
0x00f49   81 be ff a1 ce 9a f2 11 ff
0x05a83   01 03 05 07 0a 0d 11 16 1c 23 2f 39 45 55 69 87    a ramp
0x0759e   81 e4 81 e6 82 9b 82 9e 82 a1 ...
0x04a50   01 05 01 df 01 0f 70 b2 01 08
```

The `01 03 05 07 0a 0d 11 16 1c 23 2f 39 45 55 69 87` run at `0x05a83` is a
smoothly accelerating sequence - the shape of a lookup or a calibration curve.

None of this is decoded. It is recorded as: **the structure is a header, a small
bidirectional table, and a handful of fixed-stride records**, and it carries far
less state than its 512 KiB would suggest.

## 5. What this settles, and what it does not

**Settles:** there is no large register snapshot here to mine for battery or
charger state. Anyone hoping to read a live VBAT out of `sbl_pmic_dump.bin` -
which is the reason `docs/19` and `docs/15` §2 were interested in it - will not
find one. The 14 values in the `0x00xx` group are the entire PMIC-side content,
and they do not include a plausible voltage reading.

**Does not settle:**

- whether the second SID being all-zero is meaningful;
- what the `0x16 01` records are - the counter and stride suggest a request log,
  and `11 07` repeated may be a command id;
- whether the region is truncated at capture time or naturally this sparse.

## 6. Why this was worth doing

`docs/42` ranks four routes to a PBL-level session, and route A (bump) is blocked
by a spent HELLO with the only untested fix being a true power-down. Knowing
whether the PMIC ever reports a genuine power-off state would have helped judge
that. This dump does not contain it, so:

- the "is a true off state reachable" question cannot be answered from captured
  memory, and
- it has to be answered by observation - watching whether the device leaves the
  bus and stays away, which is exactly what `tablet.py watch` records.

That is a negative result with a use: it closes an avenue instead of leaving it
as a vague hope, and it points the question back at a measurement the owner can
make.
