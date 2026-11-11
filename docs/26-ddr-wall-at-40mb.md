# DDR is readable to 40 MiB, and then it is not

The single most precise measurement in this project, obtained via `QSaharaServer` over a
COM port after the driver switch.

---

## 1. How it was obtained

The vendor toolchain, working in the COM driver world, entered `SAHARA_MEMORY_DEBUG` and
began dumping every region the device declared. For DDR CS0 it walked the address space
in 1 MiB requests:

```
Sent SAHARA_MEMORY_READ, address 0x80000000, length 0x100000
Sent SAHARA_MEMORY_READ, address 0x80100000, length 0x100000
...
Sent SAHARA_MEMORY_READ, address 0x82700000, length 0x100000
Sent SAHARA_MEMORY_READ, address 0x82800000, length 0x100000
```

and the responses:

```
0x80000000  ..  0x82700000   ->  524288 bytes each   (success)
0x82800000                   ->  0 bytes             (nothing, repeatedly)
```

## 2. What that means

**DDR CS0 answers for exactly 40 MiB (0x2800000), and not one byte beyond.**

This is not a limitation of the crash handler's region table — the handler offered
`0x80000000` with a length of `0x80000000` (2 GiB) and happily issued reads across the
whole range. It is not a tool limitation — the tool is the vendor's own.

The device accepts the request at `0x82800000` and returns nothing. That is the
signature of a **read that cannot be serviced**, and every subsequent request at that
address behaves identically.

## 5. The other seven windows are not data

The dump wrote 14 GB across seven files. Sampling each at offset 0 and at 1 GiB:

```
DDRCS1_0   head 0/65536 signal bytes   mid 0/65536
DDRCS1_1   head 0/65536                mid 0/65536
DDRCS1_2   head 0/65536                mid 0/65536
DDRCS2_0   head 0/65536                mid 0/65536
DDRCS2_1   head 0/65536                mid 0/65536
DDRCS2_2   head 0/65536                mid 0/65536
DDRCS2_3   head 0/65536                mid 0/65536
```

where "signal" counts bytes that are neither `0x00` nor `0xFF`. All zero.

**Those 14 GB are `0xFF` fill — unmapped space.** `QSaharaServer` wrote whatever it
received without distinguishing data from emptiness, which is why the files are full size
and meaningless.

So the corrected picture is sharper than the first reading:

| window | declared | actually readable |
|---|---|---|
| DDRCS0_0 `0x80000000` | 2 GiB | **40 MiB of real data**, then nothing |
| DDRCS1_0 `0x880000000` | 2 GiB | `0xFF` throughout |
| DDRCS1_1 `0x900000000` | 2 GiB | `0xFF` throughout |
| DDRCS1_2 `0x980000000` | 2 GiB | `0xFF` throughout |
| DDRCS2_0 `0xa00000000` | 2 GiB | `0xFF` throughout |
| DDRCS2_1 `0xa80000000` | 2 GiB | `0xFF` throughout |
| DDRCS2_2 `0xb00000000` | 2 GiB | `0xFF` throughout |
| DDRCS2_3 `0xb80000000` | 2 GiB | `0xFF` throughout |

**The machine declares 16 GiB of DDR and presents 40 MiB of working memory.**

That is not a subtle fault. It is the difference between a device that can host a
programmer with buffers and one that cannot.

## 6. Why this matters more than anything else measured

Every DDR hypothesis in this project can now be evaluated against a number:

| earlier observation | now explained |
|---|---|
| "DDR does not answer in the crashdump" (`07-dead-ends.md` §G) | true only beyond 40 MiB; it answers perfectly below that |
| `ddr_near_probe.py` found real data to `0x200000`, then zeros, then `0xFF` | consistent — the 2 MiB probe was well inside the working range |
| `ddr_map_probe.py` sampled at 128 MiB stride and found only the first sample readable | consistent — every other sample was past 40 MiB |
| the trainer's stage list lives in SHRM_MEM, not in DDR | consistent — SHRM is a separate region that works |
| the programmer is accepted, runs ~98 ms, then stops | **now has a candidate cause**: it needs a working DDR and the DDR it is given is 40 MiB, not the 2 GiB the table claims |

## 4. The candidate explanation for the whole failure

The Firehose programmer is loaded into DRAM and runs from it. It also needs to allocate
buffers — for the XML transport, for the storage read/write path, and for whatever it
initialises at startup.

The device declares **eight** DDR windows of 2 GiB each in its own memory table:

```
DDRCS0_0  0x80000000  2 GiB
DDRCS1_0  0x880000000 2 GiB
DDRCS1_1  0x900000000 2 GiB
DDRCS1_2  0x980000000 2 GiB
DDRCS2_0  0xa00000000 2 GiB
DDRCS2_1  0xa80000000 2 GiB
DDRCS2_2  0xb00000000 2 GiB
DDRCS2_3  0xb80000000 2 GiB
```

Seven of those eight dumped **fully, 2 GiB each** — 14 GB of data. Only `DDRCS0_0` stops
at 40 MiB.

So the machine's memory is not globally broken. **One window is truncated.** That points
at a specific thing: the first 40 MiB of CS0 is where the bootloader, the crash handler
and the programmer themselves live, and something about that window's mapping is
incomplete.

An out-of-memory condition inside the programmer, caused by it believing it has 2 GiB of
contiguous DDR at `0x80000000` when only 40 MiB answers, would produce exactly the
observed behaviour: accepted, runs briefly, stops with no output.

## 5. What is not yet established

- Whether the truncation is in the mapping, in the DDR training result for that rank, or
  in the physical device.
- Whether the programmer actually allocates beyond 40 MiB. It runs for ~98 ms, which is
  short for a large allocation, so this is a hypothesis and not a conclusion.
- Whether `DDR_DATA.BIN` (the DDR training data region the table declares at
  `0x1000080000`) shows a partial or failed training result. It has not been read yet —
  the dump stalled before reaching it.

## 6. What to do with this

The immediately useful artefact is `DDR_DATA.BIN` — the region the table labels
**"DDR Training Data"**, at `0x1000080000`, length `0x40000`. If training completed for
all ranks, that data will describe 8 windows. If one rank failed, it will describe seven.

That is a 256 KiB read and it answers the question directly. It must be done in a fresh
session, because the current one has already consumed its HELLO and stalled at the wall.

## 7. Method note

This number was invisible to the custom tooling. `mem_read` in
`crash_region_probe.py` returns `b""` on timeout, and the callers treated that as "not
exposed" — which was recorded, correctly but unhelpfully, as "the crash handler does not
expose that range".

The vendor tool distinguishes the cases: it logs the request, logs `Received 0 bytes`,
and keeps going. That made it possible to see that the *same* request works at
`0x82700000` and returns nothing at `0x82800000` — one megabyte apart.

The lesson repeats one already learned twice in this project: when a measurement says
"nothing happened", the tool may be reporting its own limitation. A tool that logs what it
asked for turns that into a fact about the device.
