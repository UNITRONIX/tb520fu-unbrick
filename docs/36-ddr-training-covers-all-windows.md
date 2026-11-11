# DDR training data describes all eight 2 GiB windows: the DRAM is not the fault

`27-ddr-is-a-sparse-map.md` §5 named the discriminator for the open question and
could not obtain it. It is answerable from a 4 KiB sample already in this
repository.

---

    10|## 1. The question, as it was posed

Two explanations survived and the host could not separate them:

- **a)** the crash handler only maps 40 MiB of CS0 by design, and the real DRAM is
  fine - so the 40 MiB limit says nothing about the programmer's failure;
- **b)** CS0 genuinely only trains to 40 MiB and the rest of the declared 16 GiB is
  absent - so the programmer runs out of the memory it was promised.

The stated discriminator was `DDR_DATA.BIN`, "DDR Training Data", on the grounds
that if it describes all eight windows then DDR is fine.

    20|## 2. The measurement

`scripts/crash_region_probe/sample_0x1000080000_DDR_DATA.BIN.bin` — 4 KiB, taken
from the region the table calls `DDR_DATA.BIN`, header decoding as DDR firmware
version **102.6.0** (the same version `SHRM_MEM` reports).

Scanning it as 64-bit words:

```
value 0x0000000080000000  (2 GiB)  appears 8 times
offsets: 0x150 0x158 0x160 0x168 0x170 0x178 0x180 0x188   (contiguous)
```

Eight consecutive 2 GiB entries. The memory table declares exactly **eight** DDR
windows, each exactly 2 GiB:

```
DDRCS0_0  0x080000000  0x80000000
DDRCS1_0  0x880000000  0x80000000
DDRCS1_1  0x900000000  0x80000000
DDRCS1_2  0x980000000  0x80000000
DDRCS2_0  0xa00000000  0x80000000
DDRCS2_1  0xa80000000  0x80000000
DDRCS2_2  0xb00000000  0x80000000
DDRCS2_3  0xb80000000  0x80000000
```

    40|Eight declared windows, eight training-data entries of the declared size, in a
contiguous block. 8 × 2 GiB = **16 GiB**, which is the capacity the device
reports.

Also present, immediately after the size block, is a run of six `0xA` values at
`0x198`-`0x1B8` — consistent with a per-window or per-rank parameter, though its
meaning is not decoded.

## 3. What this settles, and what it does not

**Settles:** the training data describes the full 16 GiB, all eight windows. So
(b) is not supported. The DRAM is not partly absent in the sense of the firmware
having configured only part of it; the configuration covers everything the device
declares.

    55|**Does not settle:** why six of those eight windows read as `0xFF` through the
crash handler. That remains an exposure property — what the handler will serve —
and the two are different statements. A window that is configured but not mapped
into the crash dump's view answers with fill, exactly as observed.

So the correct reading is now:

```
training data describes 8 x 2 GiB  ->  firmware believes it has all 16 GiB
6 of 8 windows answer 0xFF         ->  the crash handler does not expose them
40 MiB of CS0 answers              ->  the handler exposes a limited slice of CS0
```

## 4. Consequence for the programmer hypothesis

`26-ddr-wall-at-40mb.md` proposed that the programmer dies because it believes it
has 2 GiB and only 40 MiB answers. That was already weakened in `27` §4 and is
weakened further here: the firmware's own training record covers the full
capacity, so a memory-starvation failure would have to occur *during* the
programmer's own re-training, not because the platform under-reports its DRAM.

    75|That keeps the failure inside `sbl1_ddr_init` in `16-firehose-bringup.md` §7 — the
one gap in an otherwise complete chain — rather than moving it to the hardware.

## 5. Provenance note

This sample was captured by `crash_region_probe.py`, which walks the memory table
in **declaration order**. `DDR_DATA` is entry 28 there, well before any 2 GiB
window is touched. `30-dump-order-blocks-ddr-data.md` generalised from the vendor
tool's behaviour to the protocol; the protocol has no such constraint, which is
why this data already existed while the document said it could not be obtained.
See `33-ddr-data-is-reachable.md`.
