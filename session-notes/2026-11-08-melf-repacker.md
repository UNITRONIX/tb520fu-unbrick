# MELF REPACKER — results and conclusions

*Original: `MELF_REPACKER.md`. Translated faithfully.*

Date: 2026-11-08 ~00:50

---

## 1. Goal

Build a melf (the format PBL accepts) with a **qtestsign-signed** firehose image inside
— given that PBL rejects a plain ELF64 (`0x29`), while the melf passes the transfer
(`END 0x0`) but firehose does not start.

## 2. What we established about the melf structure

Tool: `melf_tool.py info` / `split` / `verify`

```
file      : xbl_s_devprg_ns.melf
size      : 1 569 028 B
sha256    : 3f6184f972eb413e7688fb5fae7fe88f...

=== OUTER HEADER (wrapper) ===
  class    : ELF32
  machine  : 0x01 EM_ARM (32-bit)
  entry    : 0x22126000
  phoff    : 0x34
  phnum    : 2
  ph[0] off=0x74   filesz=0x1000 (4096)  -> 0x22126000
  ph[1] off=0x1074 filesz=0x28C  (652)   -> 0x22283000
  -> phdrs cover 0x0 .. 0x1300

=== INNER ELFs (5 of them) ===
  [0] @0x0000000  ELF32  ARM      entry=0x22126000   4 864 B
  [1] @0x001300   ELF32  0xF3     entry=0x20412D00   203 888 B
  [2] @0x032F70   ELF64  AArch64  entry=0x14825FA8   908 256 B   XBL core
  [3] @0x110B50   ELF64  AArch64  entry=0x149997A8   303 096 B   FIREHOSE
  [4] @0x15AB48   ELF64  ARM      entry=0x1494E000   148 924 B   DDR training
```

## 3. KEY FINDING

**Image [3] is BIT FOR BIT identical to `prog_firehose_ddr.elf`.**

```
standalone : 303 096 B  sha=232724FF2EFC9CB4BFB8D631537B4A0D...
img3       : 303 096 B  sha=232724FF2EFC9CB4BFB8D631537B4A0D...
IDENTICAL : True
```

So `prog_firehose_ddr.elf` **is exactly the same firehose code** that sits in the melf
at position [3]. The separate file is rejected (`0x29`) because PBL requires
**packaging in a melf**, not because the code is bad.

## 4. What we built

Tool: `build_signed_melf.py`

Strategy: take the original melf, **replace only image [3]** with the qtestsign-signed
version, leave everything else unchanged.

```
wrapper (ELF32)  : 4 864 B      <- unchanged
img1 + img2      : 1 112 144 B  <- unchanged
firehose         : 303 096 B    -> 303 104 B (signed, +8 B)
img4 + padding   : 148 924 B    <- unchanged

RESULT: xbl_s_devprg_ns_SIGNED_FH.melf   1 569 036 B (+8 B)
sha256: 647fdbe13d8dfc0934c30ea9cc68f49fbb4c1d44769bf0cefd11f830439c9522
```

Verification:

```
wrapper unchanged          : True
img1+img2 unchanged        : True
new firehose written       : True
img4 unchanged             : True
all phdrs within bounds    : True
```

**ELF32 wrapper unchanged → format preserved. Signed firehose inside.**

## 5. Variants ready for testing

```
xbl_s_devprg_ns_SIGNED_FH.melf       1 569 036 B   firehose v7 (prog)
xbl_s_devprg_ns_SIGNED_FH_v6.melf    1 569 036 B   firehose v6 (prog)
```

## 6. Test status

**The test was NOT executed.** After a restart the tablet **did not appear on USB** in
any mode:

```
9008: False   900E: False
PnP 05C6: none
PnP 17EF: none
PnP unknown devices: none (only AMD SMBus and KDNET, unrelated)
```

Previously the tablet always returned to 900E after ~15 s. Now it **does not return**.

Possible causes:

1. The tablet actually powered off and is charging (the earlier "cannot be turned off"
   may have been a cycle that ended)
2. Battery below the boot threshold
3. Cable disconnected

## 7. What to do when the tablet returns

```powershell
cd <KIT_DIR>
python test_signed_melf_2026-11-08.py
```

The script waits for the device, bumps, sends both variants and reports:

- `END 0x0` + firehose responds → **write ABL immediately**
- `END 0x0` + silence → the signature was not the problem (as before)
- `END 0x23` → hash table mismatch
- `END 0x29` → PBL rejects the signature
- `END 0xD` → transport

## 8. Limitation of the method

Replacing image [3] **does not change the wrapper**, so the melf grows by 8 B and image
[4] shifts by 8 B. If PBL addresses images by **fixed offsets** from a table in the
wrapper, that shift could break it. In that case one would have to:

- either sign the image so it is exactly 303 096 B (padding),
- or update the offset table in the wrapper (requires reverse-engineering the img1
  structure).

That is a real risk, but the test settles it.

## 9. Files

```
melf_tool.py                     info / split / patch / verify
build_signed_melf.py             builds a melf with a signed firehose
test_signed_melf_2026-11-08.py   test on the tablet
melf_parts/                      5 extracted images
xbl_s_devprg_ns_SIGNED_FH.melf   ready (v7)
xbl_s_devprg_ns_SIGNED_FH_v6.melf ready (v6)
```

---

> **Retrospective note:** the `+8 B` shift in §8 was a legitimate concern, and the
> follow-up session addressed it by trimming 8 bytes of trailing zeros to keep the total
> size identical. The result was unchanged (`0x21` at the same byte), which is what
> finally proved the shift was irrelevant — the check is over the blob's content, and
> the content had changed. See
> [`2026-11-08-melf-dead-end.md`](2026-11-08-melf-dead-end.md).
