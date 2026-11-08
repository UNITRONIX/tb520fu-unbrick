# MELF — why swapping the image does not work (CLOSED)

*Original: `MELF_DEAD_END.md`. Translated faithfully.*

Date: 2026-11-08, after the test on a charged tablet.

---

## 1. The decisive test

Tablet after **9 h of charging** — the control passed cleanly:

```
CONTROL (original melf):
  bump HELLO ver=2 mode=2
  HELLO ver=3 mode=0
  END status=0x0   bytes=1554996/1569028
  DONE_RSP cmd=0x6
  -> done_ok
```

The tablet is **fully functional**. Zero power problems.

The signed melf (identical size, 8 B of zeros trimmed):

```
SIGNED:
  END status=0x21   bytes=1109804/1569028
  -> end_0x21   (3 times identically)
```

## 2. What the number 1 109 804 shows

```
1 109 804 B   <   1 117 008 B   = offset of the firehose image (0x110B50)
```

**The transfer breaks inside image [2] — XBL core — which is UNTOUCHED.**

That proves PBL verifies the **integrity of the whole blob at once**,
not of individual images. Changing one image breaks the hash of the whole.

## 3. Is the hash somewhere in the file? NO

Checked (tool `find_hashes.py`):

| sought | result |
|---|---|
| SHA256 of each image (full) | **ABSENT** |
| SHA256 of each image (after stripping FF) | **ABSENT** |
| MD5 of each image | **ABSENT** |

The wrapper (image [0], 4 864 B) is a clean ELF32:

```
0000  7f 45 4c 46 01 01 01 00 ...   .ELF............
0010  02 00 01 00 01 00 00 00 ...   (type=EXEC, machine=ARM)
0020  05 00 00 00 34 00 20 00 ...   (e_version=5, phoff=0x34, phentsize=32)
0030  00 00 00 00 01 00 00 00 ...   ph[0]: type=1 off=0x74 filesz=0x1000
0050  01 00 00 00 01 00 00 00 ...   ph[1]: type=1 off=0x1074 filesz=0x28C
```

- 2 program headers
- from offset `0x94` to `0x1000` — **all zeros**
- region `0x1000..0x1300` — **empty**

**The hash is not stored in the file.** It is computed inside PBL and compared against
a structure we cannot see.

## 4. Why qtestsign does not help

qtestsign signs **a single ELF file** (it adds an MBN header + hash table + certificates
for **that one ELF**).

A melf is a **container** of 5 images. Signing the container would require:

1. a structure describing all 5 images,
2. a hash table for each of them,
3. placing it where PBL expects it.

That structure is not in the file — so there is nothing to compute.

## 5. Conclusions — three layers, all closed

| path | status | reason |
|---|---|---|
| sign `prog_firehose_ddr.elf` | **CLOSED** | `0x29` after 64 B — PBL requires the melf format |
| swap an image inside the melf | **CLOSED** | `0x21` — whole-blob hash |
| build our own melf | **CLOSED** | no structure and no key |

## 6. What this means for the whole matter

**The software path is exhausted.** Not for lack of ideas, but because of cryptographic
integrity verification that cannot be bypassed without Qualcomm's key.

Everything that could be checked without opening the case was checked:

| what | result |
|---|---|
| Sahara transport | ✅ works (full transfer, DONE_RSP) |
| framing, ZLP, reset | ✅ fixed |
| fastboot | ❌ does not come up (ROCKNIX ABL does not boot Android) |
| ABL menu | ❌ keys not read (AYANEO mapping ≠ Lenovo) |
| logo window | ❌ device absent from USB (0.15 ms measurement) |
| qtestsign signature | ❌ PBL rejects the ELF64 format |
| substitution in the melf | ❌ PBL verifies the whole blob |
| battery / DBC | ✅ excluded (9 h charging, control OK) |

## 7. What remains

1. **Test-point EDL** — a real 9008 from PBL, not via crashdump.
   Requires opening the case (loss of warranty).
2. **Service** — with a ready report: what is broken (ROCKNIX ABL on both slots), what
   not to try, which payloads to write.
3. **Wait** — until a public programmer/melf for SM8650 Lenovo with the right signature
   appears.

## 8. Payloads ready for the service

```
stock_abl_a.img   1 048 576 B   sha256=4E13E55E...   ABL from ZUI 17.5.10.096
stock_abl_b.img   1 048 576 B   sha256=2E3D5173...   ABL from ZUI 18.5.10.037

abl_a: LUN 4, start_sector 95238,  256 sectors × 4096 B
abl_b: LUN 4, start_sector 437686, 256 sectors × 4096 B
```

That is everything the service needs. Writing those two files over EDL takes 30 seconds
— everything else was the road to obtaining write mode.
