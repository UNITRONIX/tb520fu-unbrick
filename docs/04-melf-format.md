# The melf container

`xbl_s_devprg_ns.melf` is not a program. It is a **container holding five separate
ELF images**, plus trailing padding. Understanding this is what made the whole
failure legible.

Everything here is reproducible with [`scripts/melf_tool.py`](../scripts/melf_tool.py).

---

## 1. Outer anatomy

```
file      xbl_s_devprg_ns.melf
size      1 569 028 B
sha256    3f6184f972eb413e7688fb5fae7fe88f2f4ee0ab09b6b58b551f7cad22e89e69
```

```
0x000000 ┌─────────────────────────────────┐
         │ ELF32 wrapper (4 864 B)          │  ARM, entry 0x22126000
0x001300 ├─────────────────────────────────┤
         │ image [1]  ELF32, machine 0xF3   │  203 888 B
0x032F70 ├─────────────────────────────────┤
         │ image [2]  ELF64 AArch64         │  908 256 B   XBL core
0x110B50 ├─────────────────────────────────┤
         │ image [3]  ELF64 AArch64         │  303 096 B   ★ FIREHOSE
0x15AB48 ├─────────────────────────────────┤
         │ image [4]  ELF64 ARM             │  148 924 B   DDR training
0x1A0004 ├─────────────────────────────────┤
         │ padding, trailing 14 032 B       │  never requested by Sahara
0x1F0004 └─────────────────────────────────┘
```

---

## 2. The wrapper

The first 4 864 bytes are a genuine ELF32 with two program headers:

```
class       ELF32
machine     0x01  EM_ARM
type        2     EXEC
entry       0x22126000
phoff       0x34
phnum       2

ph[0]  off=0x74    filesz=0x1000  → vaddr 0x22126000
ph[1]  off=0x1074  filesz=0x28C   → vaddr 0x22283000
```

Together the two headers cover `0x0` … `0x1300`. The interior breaks down as:

| Range | Size | Content |
|---|---|---|
| `0x0000`–`0x0094` | 148 | ELF header + 2 program headers |
| `0x0094`–`0x1000` | 3 948 | zeros |
| `0x1000`–`0x1074` | 116 | zeros |
| `0x1074`–`0x1300` | 652 | **ph[1] payload — a tag/length metadata blob, 561 non-zero bytes** |

**CORRECTION (important, and it corrects our own earlier notes):** an earlier
analysis stated that the region `0x1000..0x1300` was empty. That is wrong. The
sub-range `0x1074..0x1300` is ph[1]'s payload and is **not** padding:

```
82 01 88 02 01 00 01 00 02 00 00 00 91 82 74 00 01 83 04 00 01 00 00 00
51 83 04 00 37 00 00 00 52 83 04 00 01 00 00 00 80 83 08 00 01 84 04 00
ff ff 0c a0 84 83 4c 00 40 84 04 00 05 00 00 00 41 84 40 00 bb 42 9d cd
...
```

It begins with a **little-endian** TLV header `tag=0x0182 len=648`, which accounts for
all 652 bytes (`4 + 648`). Reading it as big-endian (`tag=0x8201 len=34818`) overflows
the region and is wrong.

**The schema is decoded.** The header is `u16 tag | u16 len`, both little-endian, and
every value is padded to a 4-byte boundary (`align4`). This is why a naive 8-byte
tag/length walk failed: it consumed 8-byte headers and never resynchronised.
`scripts/tlv_parse.py` walks the whole region and consumes **652/652 bytes**:

```
0x1074 tag=0x0182 len=648   container(4 children)
  0x1078 tag=0x0001 len=1     value=02
  0x1080 tag=0x8291 len=116   container(5 children)
    0x1084 tag=0x8301 len=4     value=01000000
    0x108c tag=0x8351 len=4     value=37000000
    0x1094 tag=0x8352 len=4     value=01000000
    0x109c tag=0x8380 len=8     value=01840400ffff0ca0
    0x10a8 tag=0x8384 len=76    container(2 children)
      0x10ac tag=0x8440 len=4     value=05000000
      0x10b4 tag=0x8441 len=64    value=bb429dcd...      <- SHA-512, see below
  0x10f8 tag=0x81ff len=136
  0x1184 tag=0x8080 len=376   container(5 children)
    0x1188 tag=0x8101 len=4     value=01000000
    0x1190 tag=0x8102 len=4     value=01000000
    0x1198 tag=0x8103 len=4     value=02000000
    0x11a0 tag=0x8180 len=208   container
    0x1274 tag=0x81ff len=136
```

### The 0x8441 field IS a digest — of the wrapper

Measured, byte for byte:

```
region   : 0x0074 .. 0x1073   (4096 B = wrapper ph[0], type=LOAD, off=0x74, filesz=0x1000)
sha512   : bb429dcd4d326c750057c33438820a282b7ffb61f910dda9c7675598ec7ab5787
            d9d446d185b0b5def0a04d19fba1835966835688316027eb6e3d28804c1bedf
TLV 0x8441: bb429dcd4d326c750057c33438820a282b7ffb61f910dda9c7675598ec7ab5787
            d9d446d185b0b5def0a04d19fba1835966835688316027eb6e3d28804c1bedf
identical: True
```

Reproduce: `scripts/hash_sweep.py`. The neighbouring `0x8440` value `5` is almost
certainly the algorithm id (5 = SHA-512), though that mapping is an inference, not a
measurement.

So the earlier claim "no digest of any obvious byte range under any algorithm" was
wrong for this field. Correct statement: the field is a SHA-512 **of the wrapper
image**, i.e. of the TLV's own container. It protects the metadata block, not the
five inner images.

### The two 0x81FF blocks are not image digests

Both are 136 bytes and share a layout of `[u32 len][64 B][u32 len][64 B]`:

```
0x10f8  len1=195  len2=427
0x1274  len1=492  len2=307
```

Tested against SHA-512/SHA3-512/BLAKE2b/SHA-384 of: all five ELF images (raw,
`0xFF`-stripped, `0x00`-stripped), each program header segment of each image, the
whole file, the TLV region, the wrapper and concatenations of the TLV children —
**84 candidates, 9 algorithms, zero matches**. Whatever those two blocks describe, it
is not an inner-image digest.

### What the blob is, then

- A **constant** identifier block: bit-identical across ZUI 17.5.10.096 and
  ZUI 18.5.10.037 (see §5), so it does not describe build-varying content.
- It carries the only self-integrity check in the wrapper (SHA-512 over ph[0]),
  plus platform constants: `0x8351 = 55`, `0x8352 = 1`, `0x8301 = 1`, and the pair
  `0x8511 = 0x12345678` (sentinel) / `0x8510 = 0x0000FFFF`.

This matters because it bounds one of our conclusions. "There is no hash table in the
file" was too strong, and is now replaced by a measured statement:

> The wrapper carries a SHA-512 of its own 4096-byte payload (tag `0x8441`), verified
> byte-for-byte. No per-image digest of the five inner images exists anywhere in the
> file under 9 algorithms and 84 candidate regions.

What survives unchanged is the *empirical* result: substituting an image gives
`0x21` at an offset before the substitution, so modifying the file cannot fix it,
whatever that blob contains. The experiment does not depend on understanding it.

The rest of the wrapper interior, `0x94`–`0x1074`, is genuinely 4 064 bytes of zeros.
There is no certificate and no certificate chain in this region, which is why a
qtestsign-signed inner image has nothing to anchor to.

---

## 3. The five images

| # | Offset | Class | Machine | Entry | Size | What it is |
|---|---|---|---|---|---|---|
| 0 | `0x000000` | ELF32 | `0x01` ARM | `0x22126000` | 4 864 | wrapper / SBL loader stub |
| 1 | `0x001300` | ELF32 | `0xF3` (vendor) | `0x20412D00` | 203 888 | vendor-specific descriptor blob |
| 2 | `0x032F70` | ELF64 | `0xB7` AArch64 | `0x14825FA8` | 908 256 | **XBL core** |
| 3 | `0x110B50` | ELF64 | `0xB7` AArch64 | `0x149997A8` | 303 096 | **Firehose programmer** |
| 4 | `0x15AB48` | ELF64 | `0xB7` AArch64 | `0x1494E000` | 148 924 | **DDR training** (dcb, pre-DDR DTB, PLL/DRAM) |

Machine `0xF3` is outside the standard `EM_*` range; it is a Qualcomm vendor value.

---

## 4. Image 3 is exactly `prog_firehose_ddr.elf`

This is the finding that reframed everything:

```
standalone prog_firehose_ddr.elf : 303 096 B
                            sha256 = 232724ff...
melf image [3] @0x110B50         : 303 096 B
                            sha256 = 232724ff...
IDENTICAL: True
```

**Bit for bit.** The standalone file that the device rejects with `0x29` is the
*very same code* that the device accepts perfectly well when it arrives inside the
melf.

So the device was never rejecting the Firehose program. It was rejecting the
**container**. The programmer is fine; the envelope is wrong.

Practical consequence: no amount of re-signing or modifying `prog_firehose_ddr.elf`
could ever help. It is the wrong artifact to work on.

---

## 5. The hash-table problem

Modifying image [3] inside the melf and resending produces:

```
END_TRANSFER  status=0x21  bytes=1109804/1569028
```

`0x21` is `HASH_TABLE_AUTH_FAILURE`. Two facts about that offset matter:

```
1 109 804 B   bytes transferred when rejected
1 117 008 B   where image [3] begins
```

The rejection happens **7 204 bytes before** the modified image is reached. The
device is checking something much earlier and refusing the whole blob.

### So where is the hash?

Hunted, systematically:

| Target | Method | Result |
|---|---|---|
| SHA-256 of each image, full | search the digest bytes across the whole file | **not present** |
| SHA-256 of each image, trailing `0xFF` stripped | same | **not present** |
| MD5, SHA-1, SHA-224/384/512, SHA3-256, BLAKE2b, CRC32 of each image | same | **not present** |
| Any table of image offsets | search for each inner offset as 32-bit and 64-bit LE | **not present** |
| Certificate material in the wrapper interior | byte scan of `0x94`–`0x1074` | **4 064 bytes of zeros** |
| Every program-header segment of every image, raw / `0xFF`-stripped / `0x00`-stripped | `scripts/hash_sweep.py`: 84 candidates × 9 algorithms against all hash-sized TLV values | **no match** |

`scripts/find_hashes.py` reproduces the first five rows; `scripts/hash_sweep.py`
reproduces the last one.

The one digest that *does* exist is in the metadata blob and covers the wrapper
itself, not an image — see "The 0x8441 field IS a digest" above.

### The one region we did not decode

None. The `0x1074`–`0x1300` blob is now decoded, including its schema, its container
nesting and its one digest. See §4.

### Why per-image replacement cannot work

If the loader validates the container as a unit, then replacing one image breaks
the whole — and this is measured, not assumed: the rejection lands thousands of bytes
before the modified image. Building a valid modified melf would require:

1. knowing the exact structure PBL hashes over,
2. a hash table in the format it expects, in the location it expects,
3. and a signature over that, from Qualcomm's key — not qtestsign's.

Point 3 is unavailable, so the path ends regardless of 1 and 2. Point 1 is now partly
answered — the inner images carry their own Qualcomm hash segments (see §6), and the
wrapper carries only a SHA-512 over itself — but that does not open the path, because
point 3 does not depend on it.

---

## 6. The metadata blob is identical across builds

Three independently obtained copies of the same programmer:

| package | size | file SHA-256 | TLV SHA-256 (`0x1074`–`0x1300`) |
|---|---|---|---|
| ZUI 18.5.10.037 (A17, RSA) | 1 569 028 | `3f6184f972eb413e…` | `d862fb4982821d99…` |
| ZUI 17.5.10.096 | 1 569 028 | `ba72961ce341d4ed…` | `d862fb4982821d99…` |
| `stock_18.5_ref` (device backup) | 1 569 028 | `3f6184f972eb413e…` | `d862fb4982821d99…` |

Measured with `scripts/verify_tlv.py`. Between 18.5.10.037 and 17.5.10.096:

```
differing bytes total : 33 779
first difference      : 0x314CC
last difference       : 0x17E534
differences inside TLV: 0
```

So the payload bytes differ substantially (the inner images are different builds)
while the 652-byte metadata block is **bit-for-bit identical** — including the
SHA-512 at `0x8441`, which therefore covers only the wrapper and never changes.

Consequence: the blob cannot be a table of inner-image digests. If it were, it would
have to differ between builds whose images differ. This is now a measurement, not an
inference. What the blob holds is build-invariant platform data plus a self-check.

   270|---

## 7. `xbl_s.melf` is a prefix

`xbl_s.melf` is 1 117 008 B — exactly the offset where image [3] begins.

It is the container **up to but excluding** the Firehose programmer: wrapper,
image [1], image [2]. Useful for probing how far the device will go without ever
running Firehose, and for testing upload code without a full 1.5 MB transfer. It
cannot flash anything.

---

## 8. Why Sahara asks for 1 554 996 of 1 569 028 bytes

The device requests images by offset and length, not the whole file. The final
14 032 bytes are padding that no image needs. The set of requests sums to
1 554 996 B.

This is normal. A health check should compare `high_water` (the highest offset
reached) against the file size, not the byte count against the file size — the
former reaches 1 569 028, the latter never will.

Earlier notes listed the 14 032-byte difference as an unexplained anomaly and
briefly suspected a truncated final packet. It is not an anomaly.

---

## 9. Rebuilding the container

[`scripts/build_signed_melf.py`](../scripts/build_signed_melf.py) does the
mechanical part correctly: it splits at `0x1300`, `0x110B50` and `0x15AB48`,
substitutes image [3], verifies that every other region is byte-identical, and
confirms all program headers remain in bounds.

The script produces a structurally valid melf. It does not produce one the device
will accept, because of §5. It is included because reproducing the failure is how
we proved the checking happens at container level — and because anyone repeating
this work should be able to confirm the same result in minutes rather than days.

Two cautions if you extend it:

- Substituting a differently-sized image shifts image [4] and everything after it.
  If PBL addresses images by fixed offsets from a table we have not found, a shift
  breaks it. Pad to the original length if you want to eliminate that variable.
- The wrapper is left untouched by design. Any approach that *edits* the wrapper
  is working with a structure we do not understand; expect it to fail in a new way
  rather than succeed.

---

## 10. Summary

| Question | Answer |
|---|---|
| Is the melf a program? | No, a container of five images. |
| Is the Firehose inside it the same as the standalone ELF? | Yes, bit-identical. |
| Is there a hash table in the file? | The wrapper carries a SHA-512 of its own 4096-byte payload (tag `0x8441`, verified byte-for-byte). No per-image digest of the five inner images exists — 84 candidate regions × 9 algorithms, no match. See §5. |
| Why does the metadata blob not change between builds? | It is build-invariant platform data plus a self-check; bit-identical across 17.5.10.096 and 18.5.10.037 while 33 779 payload bytes differ. See §6. |
| Can one image be swapped? | No — whole-blob integrity, rejected before the swap point. |
| Can the container be rebuilt? | Mechanically yes; usefully no, without Qualcomm's key. |
