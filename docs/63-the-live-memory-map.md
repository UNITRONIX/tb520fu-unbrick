# The exposed memory map, read from the live table — and the counter is definitively outside it

`docs/62` checked `0x148F0080` against a region list assembled by hand from
documents. The **actual table the device publishes** is in the dump, and it can be
read directly. Doing so confirms the conclusion with the authoritative list rather
than a reconstructed one.

---

    10|## 1. Where the table is

Searching the DDR capture for region names (`OCIMEM.BIN`, `CODERAM.BIN`, ...) gives
several hits. The real table is at `0x81B3F008`; its entry layout, decoded:

```
qword  save_pref
qword  mem_base
qword  length
char   desc[20]
char   filename[20]
```

64 bytes per entry, 53 entries, matching the count the vendor tool reported.

```
python -c "... walk 0x81B3F008 + n*64 ..."
-> live table entries: 53
```

## 2. The complete map

```
0x0003E06000  +0x2800      IPA GSI  region          IPA_GSI.BIN
0x0003F50000  +0x5000      IPA SRAM region          IPA_SRAM.BIN
0x0003F60000  +0x18FFC     IPA HRAM region          IPA_HRAM.BIN
0x0003F81000  +0x468       IPA SEQ region           IPA_SEQ.BIN
0x0003FA0000  +0xDF00      IPA IRAM region          IPA_IU.BIN
0x0003FC2000  +0x100       IPA MBOX region          IPA_MBOX.BIN
0x000B000000  +0x18000     AOP Code RAM region      CODERAM.BIN
0x000B0E0000  +0x8000      AOP Data RAM region      DATARAM.BIN
0x000C310000..0x000C3F0000 +0x400 each   16 x MSGRAM
0x0010080000  +0x18000     DCC SRAM region          DCC_SRAM.BIN
0x00100FF000  +0x1000      DCC CFG region           DCC_CFG.BIN
0x0014680000  +0x2C000     OCIMEM                   OCIMEM.BIN
0x0017D00000  +0x10000     CPUCPFW region           CPUCPFW.BIN
0x0024020000  +0x40000     SHRM MEM region          SHRM_MEM.BIN
0x0080000000  +0x1E8       CD STRCT region          CD_STRCT.BIN
0x0080000000  +0x80000000  DDR CS0 part0 Memo       DDRCS0_0.BIN
0x00800001E8  +0x40000     CD BTDDR region          CD_BTDDR.BIN
0x00800401E8  +0x200000    CD BTIMM region          CD_BTIMM.BIN
0x00802401E8  +0x1000      CD SHIMM region          CD_SHIMM.BIN
0x0081B40410  +0x102C      CMM Script               load.cmm
0x0081B75008..0x0081B75168  6 small PMIC/reset regions
0x0081D01030  +0x1000      SMEM info                SMEM_VER.BIN
0x0081D09408  +0x300       SMEM info                SMEMINFO.BIN
0x0880000000..0x0B8000000  +0x80000000 each  7 more DDR windows
0x1000000000  +0x80000     PMIC registers           sbl_pmic_dump.bin
0x1000080000  +0x40000     DDR Training Data        DDR_DATA.BIN
```

## 3. The counter is outside all of it

```
0x148F0080 inside any exposed region?  False
```

Checked against the device's own 53-entry table, not a reconstruction. The nearest
region below is `OCIMEM` at `0x14680000 + 0x2C000`, ending `0x146AC000` - the target
is `0x244080` beyond it.

**So `dload_entry_count`, the single variable the whole EDL analysis reduced to,
cannot be read by any means currently available.** That is now established against
the authoritative source.

## 4. What the map reveals that was not used

Two observations worth keeping, both new:

- **`CD_STRCT` is `+0x1E8` bytes at `0x80000000`, and `DDRCS0_0` starts at the same
  address with a 2 GiB length.** So the crash-context region *overlaps* the DDR
  window rather than being separate - which is why `docs/54` found the same bytes at
  offset 0 in both. The table is a set of named views onto overlapping memory, not a
  partition.
- **`CD_BTDDR` at `0x800001E8` is 256 KiB** and sits immediately after the crash
  context. `docs/15` §4 tried to decode `TRN_PRINT`/`TRN_ISSUE` records and could not
  find them in `SHRM_MEM`. `CD_BTDDR` is the DDR boot-time snapshot region and has
  never been examined for those records - a concrete, bounded, unread region inside
  memory we already hold.

## 5. Status of the goal

Unchanged: `HELLO ver=3 mode=0` has not been obtained. The blocker chain is now fully
mapped:

```
gate 1  lazy initialiser               passes  (docs/61)
gate 2  skip_ddr_init_in_EDL = 0 < 2   passes  (docs/60)
gate 3  dload_entry_count >= 2         variable, and NOT readable (this document)
```

The only remaining action that can change gate 3's state is a genuine cold boot with
no warm reset before the attempt. Everything the host can do has been done.

One unread region remains inside memory already captured: `CD_BTDDR`, 256 KiB at
`0x800001E8`. It is worth reading before declaring the offline work finished, because
`docs/15` §4's failure to find training records in `SHRM_MEM` does not rule them out
of the region actually named for DDR boot data.
