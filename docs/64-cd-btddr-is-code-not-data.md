# CD_BTDDR is code, not training data — the lead is closed

`docs/63` noted `CD_BTDDR` (256 KiB at `0x800001E8`) as a never-examined region
whose name - "CD BTDDR" - suggested DDR boot-time data, and proposed checking it
for the `TRN_PRINT` / `TRN_ISSUE` records that `docs/15` §4 could not find in
`SHRM_MEM`.

It has now been examined. **It contains no data at all.**

---

    10|## 1. What is there

```
region 0x800001E8, 256 KiB
nonzero bytes      87.3 %
string search: TRN 0, REASON 0, DDR_FW 0, PLL 0, DCC 0, Vref 0,
               training 0, TRAINING 0, DDR 0
```

Zero hits for every DDR-related string. The bytes decode as ARM64:

```
0x800001e8  msr s3_0_c2_c2_2, x1
0x800001ec  msr s3_0_c2_c2_3, x2
0x800001f0  ldp x1, x2, [x0, #0x20]
0x800001f4  msr s3_0_c2_c1_0, x1
0x800001f8  msr s3_0_c2_c1_1, x2
...
0x80000218  mrs x9, s3_4_c1_c0_0          read SCTLR
0x8000021c  orr x9, x9, #0xc0000000
0x80000224  orr x9, x9, #0x2000
0x80000228  msr s3_4_c1_c0_0, x9          write SCTLR back
0x80000234  b   0x8001e940
```

That is crash-handler code: system-register writes, a `SCTLR` modify, then a branch
into the rest of the handler.

## 2. Content classification

```
4 KiB pages:  code-like 64,  high-entropy 0,  zero 0
first 256-byte fill run: none
```

All 64 pages classify as code-like. **There is no data region, no fill, no table.**
The whole 256 KiB is executable.

## 3. Why this is a closed lead rather than a surprise

`docs/63` §4 proposed the check on the reasoning that the region is named for DDR
boot data. The name is misleading: in the `ramdump_table` naming (the same table
`docs/63` decoded) the `CD_*` prefix denotes **crash-dump context**, not DDR
content:

```
CD_STRCT.BIN   0x80000000   +0x1E8      crash structure
CD_BTDDR.BIN   0x800001E8   +0x40000    crash handler, DDR-context variant
CD_BTIMM.BIN   0x800401E8   +0x200000   crash handler, IMM variant
CD_SHIMM.BIN   0x802401E8   +0x1000     crash handler, SHIMM variant
```

"BTDDR" reads as *boot-time DDR context*, i.e. **which variant of the crash handler
to run for a DDR-time fault** - not the DDR training records. Every `CD_*` region is
a code carve-out of the same handler, laid end to end from `0x80000000`.

That also explains the overlap `docs/63` noticed: `CD_STRCT`/`CD_BTDDR`/`CD_BTIMM`/
`CD_SHIMM` and `DDRCS0_0` all start at `0x80000000`-based addresses because the
`CD_*` entries are **sub-ranges of the same 2 GiB window**, each naming a slice.

## 4. Where the training outcome actually is, once more

`docs/15` §4's conclusion stands and is now stronger:

- `SHRM_MEM` holds the DDR firmware's static structures (version, stage names,
  failure vocabulary) but no instantiated records;
- `CD_BTDDR` holds code, not records;
- the `TRN_ISSUE` buffer pointers (`0x24070000`+) do not answer (`docs/15` §4);
- so **the training outcome is not recoverable from any captured region.**

That is now a closed question rather than an open one, which is worth having after
so many turns.

## 5. Status

Goal unchanged: `HELLO ver=3 mode=0` not obtained. The offline surface is now
exhausted in the following sense - every region the device exposes has been either
decoded or classified, and the two things that would have advanced the goal from
data alone (the gate 3 counter, the DDR training outcome) are both outside what can
be read.

The remaining actions are physical, and they are the same three `docs/62` listed:

1. a genuine cold boot, powered on once, no warm reset - the only route past gate 3;
2. charge the battery (`VBAT 3588mV`, `UFS Gear 1` on both logged boots);
3. the vendor procedure from a verified off state (`scripts/vendor_entry.py`).
