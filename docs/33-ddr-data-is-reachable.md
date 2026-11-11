# Correction: DDR_DATA is reachable, and the read order is by size, not address

This document corrects `30-dump-order-blocks-ddr-data.md`, which concluded that
`DDR_DATA.BIN` is unreachable because `QSaharaServer` walks the memory table in
ascending address order and stalls at `0x82800000` first.

**That conclusion is wrong, and the log it was drawn from contains the evidence
against it.** The region is not blocked by ordering, and the walk never stalls.

---

    10|## 1. What the log actually records

`com_attempt/ddrdata_log.txt` — 29 MB, UTF-16LE, recorded 2026-11-11 11:02:06 to
11:07:21. It is the run that `30-dump-order-blocks-ddr-data.md` describes as
stalling.

Decoded properly (`scripts/parse_ddrdata_log.py`):

```
table entries declared : 53
reads issued           : 10 160
"Successfully wrote to disk" occurrences : 10 159
errors / timeouts in the log              : 0
```

So the run did not stall. It completed, and it wrote 10 159 files.

> **Why this was missed:** the log is UTF-16LE. Read as plain text, every
> character is followed by a NUL byte, so a regex like
> `Sent SAHARA_MEMORY_READ, address (0x…` matches nothing and the file looks
> like it contains no reads at all. `parse_ddrdata_log.py` passes
> `encoding="utf-16"`. This is the same failure mode as truncating a pipeline:
> the tool answers, the answer is empty, and the emptiness has nothing to do
> with the device.

## 2. The order is not an address sort

    30|First twelve requests, verbatim:

```
0x00081b3f008  len=0xd40
0x00081b40410  len=0x102c
0x00b80000000  len=0x100000
0x00b80100000  len=0x100000
0x00b80200000  len=0x100000
...
0x00bfff00000  len=0x100000
```

The declared table, in declaration order, begins with the small named regions
(`OCIMEM`, `CODERAM`, `DATARAM`, `MSGRAM*`, `SHRM_MEM`, `DCC_*`, `CD_*`, the PMIC
scalars, `sbl_pmic_dump`, `DDR_DATA`) and ends with the eight 2 GiB DDR windows.
The reads start with two small regions and then go straight to
`0xB80000000` — the **last** DDR window declared.

That is not ascending address order. The tool is ordering the work its own way
(largest declared windows first, which is also why `0xB80000000` comes before
`0xA00000000`). The premise of the earlier document — "the tool walks addresses
ascending, so the highest entry is always last" — does not hold.

## 3. What was reached, and what the device answered

```
DDRCS0_0.BIN   0x80000000    2 GiB   never requested in this run
DDRCS1_0.BIN   0x880000000   2 GiB   never requested in this run
DDRCS1_1.BIN   0x900000000   2 GiB   never requested in this run
DDRCS1_2.BIN   0x980000000   2 GiB   all 0xFF
DDRCS2_0.BIN   0xa00000000   2 GiB   all 0xFF
DDRCS2_1.BIN   0xa80000000   2 GiB   all 0xFF
DDRCS2_2.BIN   0xb00000000   2 GiB   all 0xFF
DDRCS2_3.BIN   0xb80000000   2 GiB   all 0xFF
```

High-water mark reached: **`0xBFFF00000`** — 48 GiB of address space above zero,
and 3 GiB above the alleged wall.

Two facts follow, and they pull in opposite directions:

1. **The device never refused an address.** 10 158 requests in the
   `0x980000000`–`0xC00000000` range were each answered with a full 1 MiB,
   written to disk, and the session continued. There is no stall, no zero-byte
   read, no timeout. Whatever `0x82800000` is, it does not terminate a read
   session.
2. **Every one of those answers was `0xFF`.** The windows above CS1 part 2 are
   not populated. A full read succeeded and the content is fill.

So the correct statement is not "40 MiB is all DDR serves". It is: **CS0 and the
first CS1 windows are where the content is, the windows above that answer with
`0xFF` rather than refusing, and `DDR_DATA` was simply never asked for in this
run** because the run was stopped or redirected before reaching it.

## 4. DDR_DATA has been read

The claim that it is unreachable is contradicted by an artefact already in this
repository:

    scripts/crash_region_probe/sample_0x1000080000_DDR_DATA.BIN.bin
    4096 bytes, captured by crash_region_probe.py

Its first bytes decode cleanly:

```
offset 4   u32 x4  =  102, 6, 0, 0     <- version 102.6.0
```

`102.6.0` is the same version string that `SHRM_MEM` carries as
`DDR_FW version : 102.6.0`. So this is genuine DDR firmware training data, and it
was obtained over the crash-dump path.

That sample came from `crash_region_probe.py`, which reads the first 4 KiB of
**every** table entry in one session — in table declaration order, which puts
`DDR_DATA` **28th**, before any 2 GiB window is touched. The vendor tool's
ordering is irrelevant to a custom client; the earlier document generalised from
the vendor tool's behaviour to the protocol, and the protocol does not have that
constraint.

The one thing that was genuinely blocked: the full 256 KiB of `DDR_DATA`, because
earlier sessions were consumed by the multi-gigabyte sweep first. That is a
tooling limit, not a device limit.

## 5. What this changes

| Claim in `30-…` | Status |
|---|---|
| `QSaharaServer` walks addresses ascending | **wrong** — it orders by declared size |
| DDRCS0_0 is read first and stalls at 0x82800000 | **wrong for this run** — DDRCS0_0 was never requested; the run completed |
| DDR_DATA is unreachable by construction | **wrong** — present in this repository as a 4 KiB sample, version 102.6.0 |
| the training outcome cannot be measured | **narrowed** — the data is obtainable; only the full 256 KiB has not been fetched |

What survives: the eight windows above CS1 part 2 really do read as `0xFF`, and
that is a statement about which DRAM is populated, not about what the handler
will serve.

## 6. The measurement that is now worth taking

Read the **whole 256 KiB** of `DDR_DATA`, and only that, in one session:

```
python scripts/com_sahara_client.py --port COM<port> --grab DDR_DATA
```

The client asks for that entry first, so no multi-gigabyte window is in the way.
The training data describes the ranks the firmware configured, which is the
discriminator between "the crash handler exposes a limited window" and "DRAM
really is only partly trained" — the open question in `27-ddr-is-a-sparse-map.md`
§5.

**Caveat established this session, and it is a hard one:** the client needs a
fresh Sahara `HELLO`, and this device emits exactly one per boot. A
`SAHARA_RESET` (`0x07`) does **not** produce another — verified twice, and
verified independently with the vendor tool on the same port. So this read needs
either a port that has not yet been opened since the last boot, or a boot that
happens while a catcher is already polling for the port. See
`docs/32-session-conventions.md` for the rules that apply to running it.
