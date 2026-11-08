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

It begins with a plausible big-endian TLV header `tag=0x0182 len=0x0288`, which
accounts for all 652 bytes (`4 + 0x288`). Within it there is a 64-byte high-entropy
field (at offset `0x44`, under a `0x8441` tag) that looks like a digest, followed by
a further 136-byte field under `0x81FF` and a 376-byte field under `0x8080`.

**What we know about it:** it is not ASN.1 (no `30 82` in any byte order), its nested
TLVs do not parse cleanly with a naive 2-byte tag/length walk, and its 64-byte value
is not a plain sha256/sha384/sha512/sha3/blake2b/crc32 of any obvious byte range of
this file — all tested.

**What we do not know:** what it describes. It is plausibly a descriptor list, but we
never decoded it, and we do not claim it is.

This matters because it weakens one of our conclusions by exactly the right amount.
"There is no hash table in the file" is too strong. The accurate statement is:

> No per-image digest of the inner images is stored anywhere we could find, under
> any standard algorithm. A 652-byte metadata blob in the wrapper remains
> unexplored and may describe the images in a format we did not decode.

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

`scripts/find_hashes.py` reproduces all of this.

### The one region we did not decode

The wrapper's ph[1] payload at `0x1074`–`0x1300` (652 bytes) is **not** empty, contrary
to an earlier note. It is a tag/length blob with an outer header `tag=0x0182
len=0x0288` covering all 652 bytes, containing a 64-byte high-entropy field at `+0x44`
that is not a digest of any obvious byte range under any algorithm we tried.

We never decoded its schema. So the precise claim is **not** "the file contains no
metadata" but:

> No per-image digest is stored under any standard algorithm we tested, and no table
> referencing the inner image offsets exists. One 652-byte metadata blob remains
> unexplained and might describe the images in a format we did not reverse.

What does not depend on this: the substitution experiment fails with `0x21` at byte
1 109 804, before the modified image at 1 117 008. Whatever that blob is, editing the
container does not satisfy the check.

### Why per-image replacement cannot work

If the loader validates the container as a unit, then replacing one image breaks
the whole — and this is measured, not assumed: the rejection lands thousands of bytes
before the modified image. Building a valid modified melf would require:

1. knowing the exact structure PBL hashes over,
2. a hash table in the format it expects, in the location it expects,
3. and a signature over that, from Qualcomm's key — not qtestsign's.

Point 3 is unavailable, so the path ends regardless of 1 and 2. Point 1 is also
unavailable, and the unexplored metadata blob in §5 is a reminder that "we did not
find it" is not the same as "it is not there".

---

## 6. `xbl_s.melf` is a prefix

`xbl_s.melf` is 1 117 008 B — exactly the offset where image [3] begins.

It is the container **up to but excluding** the Firehose programmer: wrapper,
image [1], image [2]. Useful for probing how far the device will go without ever
running Firehose, and for testing upload code without a full 1.5 MB transfer. It
cannot flash anything.

---

## 7. Why Sahara asks for 1 554 996 of 1 569 028 bytes

The device requests images by offset and length, not the whole file. The final
14 032 bytes are padding that no image needs. The set of requests sums to
1 554 996 B.

This is normal. A health check should compare `high_water` (the highest offset
reached) against the file size, not the byte count against the file size — the
former reaches 1 569 028, the latter never will.

Earlier notes listed the 14 032-byte difference as an unexplained anomaly and
briefly suspected a truncated final packet. It is not an anomaly.

---

## 8. Rebuilding the container

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

## 9. Summary

| Question | Answer |
|---|---|
| Is the melf a program? | No, a container of five images. |
| Is the Firehose inside it the same as the standalone ELF? | Yes, bit-identical. |
| Is there a hash table in the file? | No per-image digest was found under any standard algorithm. One 652-byte metadata blob in the wrapper remains undecoded — see §5. |
| Can one image be swapped? | No — whole-blob integrity, rejected before the swap point. |
| Can the container be rebuilt? | Mechanically yes; usefully no, without Qualcomm's key. |
