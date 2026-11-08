# 2026-11-08 (late) — writing up the repo, and four corrections to my own notes

*Written while consolidating the session logs into the public repository. This entry
records not new discoveries about the device, but errors found while re-deriving old
conclusions from the files themselves.*

Four things were asserted during the write-up and then turned out to be wrong, or
less certain than stated. All are recorded here rather than quietly fixed, because the
pattern — asserting from memory, then verifying later — is the same one that produced
the original `0x23` misreading.

Three of the four were caught after being published or stated, not before. That is the
honest count.

---

## CORRECTION 1 — "the TLV blob is empty" was false; it is a 652-byte LE structure

The wrapper's `ph[1]` payload had been described as padding. Reading the bytes
disproved that immediately.

```
0x0094..0x1000   3948 B   all zeros
0x1000..0x1074    116 B   all zeros
0x1074..0x1300    652 B   561 non-zero bytes   <- ph[1] payload, NOT padding
```

The original note (`NOTES_ODKRYCIA_2026-11-08_noc.md`, discovery 8 area) said the
whole `0x1000..0x1300` range was empty. It is not. The earlier scan looked for
*non-`00`/non-`FF` runs longer than 64 bytes* starting from `0x1300`, so it never
examined this region at all.

### What the blob actually is

A tag/length structure, **little-endian, with values padded to 4-byte alignment**.
The alignment is what made the first parse attempt fail: a naive walker reading
`tag(u16), len(u16), value(len bytes)` runs off the end at the second field, because
the next tag does not begin where the value ended.

```
+0x000  tag=0x0182  len=648   container, covers all 652 bytes
  +0x004  tag=0x0001  len=1    0x02
  +0x00C  tag=0x8291  len=116  container
    +0x010  tag=0x8301  len=4    0x1
    +0x018  tag=0x8351  len=4    0x37
    +0x020  tag=0x8352  len=4    0x1
    +0x028  tag=0x8380  len=8    0x48401  0xA00CFFFF
    +0x034  tag=0x8384  len=76   container
      +0x038  tag=0x8440  len=4    0x5
      +0x040  tag=0x8441  len=64   64-byte high-entropy value
  +0x084  tag=0x81FF  len=136  136-byte opaque blob
  +0x110  tag=0x8080  len=376  container
    +0x114  tag=0x8101  len=4    0x1
    +0x11C  tag=0x8102  len=4    0x1
    +0x124  tag=0x8103  len=4    0x2
    +0x12C  tag=0x8180  len=208  container
      +0x130  tag=0x8281  len=204  container
        +0x134  tag=0x8300  len=4    0x1
        +0x13C  tag=0x8380  len=20   container
          +0x140  tag=0x8487  len=16   container
            +0x144  tag=0x8510  len=4    0xFFFF
            +0x14C  tag=0x8511  len=4    0x12345678     <- sentinel
        +0x154  tag=0x8381  len=16   container
          +0x158  tag=0x8422  len=4    0x37
          +0x160  tag=0x8423  len=4    0x4
        +0x168  tag=0x8390  len=148  container
          +0x16C  tag=0x8410  len=4    0x3
          +0x174  tag=0x8411  len=136  136-byte opaque blob
    +0x200  tag=0x81FF  len=136  136-byte opaque blob
```

Consumes exactly 652 of 652 bytes. The structure is real and self-consistent.

### The 64-byte value IS a digest — and it corrected me

My first pass concluded it was "not a digest of any byte range tried". That was true
for the ranges I tested and wrong as a conclusion, because I never tested the obvious
one.

```
region : 0x0074 .. 0x1073   (4096 B — wrapper ph[0] payload, off=0x74 filesz=0x1000)
sha512 : bb429dcd4d326c750057c33438820a282b7ffb61f910dda9c7675598ec7ab578
        7d9d446d185b0b5def0a04d19fba1835966835688316027eb6e3d28804c1bedf
TLV@0x8441: bb429dcd... (identical)
```

**It is the SHA-512 of the wrapper's own payload.** My `_dig.py` harness tested
`d[0:0x1074]` (wrapper including ELF header) and reported no match, then I wrote the
conclusion as if the range list had been exhaustive. It had not been: the matching
range, the one that corresponds to an actual program header, was missing.

The neighbouring `0x8440 = 5` is almost certainly an algorithm identifier (5 = SHA-512),
though that is inference and not measured.

So the metadata blob is **self-protecting**: it carries a digest of the block that
contains it. It says nothing about the five inner images.

### The two 0x81FF blocks are still unexplained

Both 136 bytes, sharing a layout of `[u32][64 B][u32][64 B]`.

Tested against SHA-512, SHA3-512, BLAKE2b and SHA-384 of all five images (raw,
`0xFF`-stripped, `0x00`-stripped), each program-header segment of each image, the
whole file, the TLV region, the wrapper, and concatenations of the TLV children: no
match.

That is a much stronger negative than my first attempt, because it was run as a
systematic sweep rather than a handful of guesses — 84 regions, 9 algorithms — and is
reproducible with `scripts/hash_sweep.py`.

---

## CORRECTION 2 — the TLV is identical across two different firmware builds

This is the finding that actually matters, and it was only available because two
other firmware packages happened to still be on disk.

Comparing three copies of `xbl_s_devprg_ns.melf`:

| Package | file sha256 | TLV sha256 (`0x1074..0x1300`) |
|---|---|---|
| ZUI 17.5.10.096 | `ba72961ce341d4ed…` | `d862fb4982821d99…` |
| stock 18.5 ref | `3f6184f972eb413e…` | `d862fb4982821d99…` |
| ZUI 18.5.10.037 | `3f6184f972eb413e…` | `d862fb4982821d99…` |

The two builds differ in **33 779 bytes**. A byte-range diff shows every difference
lies between `0x00314CC` and roughly `0x0318xx` — inside inner image `[1]`/`[2]`,
the SBL/XBL core region. **No difference touches the TLV.**

### Why this matters

If that 652-byte blob were a table of per-image hashes, it would have to change when
the images change. The images differ substantially between these builds. The blob
does not differ at all.

**Therefore it is not a per-image integrity table.** That is now strong evidence,
not an inference from absence.

What remains consistent with the data: it is build-independent metadata — format
version, container parameters, feature flags, DDR-related configuration, or a fixed
capability descriptor. The `0x12345678` placeholder supports the "configuration
template" reading rather than the "cryptographic commitment" one.

### What this does *not* change

The empirical result stands untouched: replacing an image inside the container gives
`0x21` at byte 1 109 804, which is thousands of bytes **before** the replaced image
at 1 117 008. Whatever verifies the container, it is not this blob, and editing the
file still cannot satisfy it.

So the conclusion "per-image substitution cannot work" is unaffected. What changes is
the *explanation*: it is not "there is no hash table in the file", it is "the table in
the file is not the thing doing the verifying".

---

## CORRECTION 3 — about the switch packet, I was wrong twice in ten minutes

This one is worth recording in full because it is the clearest demonstration of the
failure mode this project is about.

**The question:** how many bytes should the `SWITCH_MODE` packet be? The Sahara
header declares `length`, so a packet can carry a declared length of 12 while
occupying more bytes on the wire, or exactly 12.

**First assertion (in `docs/14`):** the sequence is `pack("<III", 0x0C, 12, 0)` — 12
bytes — and this matches the session that produced the log.

**Second assertion (chat, minutes later):** the log-producing script actually used
16 bytes, so my 12-byte version did not match, and the documentation was probably
wrong.

**Actual answer:** the first assertion was right, the second was wrong, and the
verification was one command that I should have run before either claim.

```
$ rg -n "SWITCH_MODE|switch" catch_usbclass_2026-11-08.py
74:        sh.cmd_modeswitch(sahara_mode_t.SAHARA_MODE_IMAGE_TX_PENDING)
```

`catch2.log` — the log with the timings and response codes — was produced by
`catch_usbclass_2026-11-08.py`, which calls `edlclient`'s helper. And that helper is:

```python
def cmd_modeswitch(self, mode):
    data = pack("<III", cmd_t.SAHARA_SWITCH_MODE, 0xC, mode)   # 12 bytes
    self.cdc.write(data)
```

Twelve bytes. Which is what `scripts/sahara_bump.py` sends. No change needed.

**Where the 16-byte variant comes from**, and why it looked authoritative:

| File | Packet | Status |
|---|---|---|
| `catch_usbclass_2026-11-08.py` | `cmd_modeswitch` → 12 B | **produced the log evidence** |
| `oneshot_2026-11-08.py:224` | `pack("<IIII", SWITCH, 12, MODE, 0)` → 16 B | outlier, one file |
| `catch_and_flash_2026-11-08.py:214` | `pack("<II", SWITCH, 12, MODE, 0)` | **broken**: 2 format specs, 4 arguments → `struct.error` at runtime |

Counted across the kit: **35 scripts** use `cmd_modeswitch` (12 bytes), one uses the
16-byte form, one is outright broken.

### The uncomfortable part

I asserted a byte-level claim from reading one file, then "corrected" it by reading a
different file, and both times stated it with confidence. The log line
`bump: switch -> 1` does not record the packet length at all — it records the *reply*.
So neither claim was supported by the log; I was inferring from whichever source file
I happened to open.

The lesson is the same one as the `0x23` misreading: **a code path that exists is not
a code path that ran.** Only the log tells you what ran, and only if the log records
the thing you think it records.

---

## CORRECTION 4 — I declared the digest "unfound" using a test that could not find it

This is the most instructive of the four, and it happened inside the same hour as
correction 3.

Having decoded the TLV and found a 64-byte high-entropy field under tag `0x8441`, I
ran a harness that hashed a list of candidate regions and reported no match. I then
wrote, in `docs/04-melf-format.md` and in a chat message, that the field was "not a
digest of any byte range we tried" and that this made the blob "build-independent
metadata".

**Both statements were wrong.**

The field is:

```
sha512(0x0074 .. 0x1073)   = bb429dcd4d326c750057c33438820a28...
TLV field @0x8441          = bb429dcd4d326c750057c33438820a28...
identical: True
```

It is the SHA-512 of the wrapper's `ph[0]` payload — a 4096-byte region that an actual
program header describes (`off=0x74 filesz=0x1000`). The blob is **self-protecting**.

### Why the harness missed it

My candidate list contained `d[0:0x1074]` — the wrapper *including* its ELF header —
and `d[0x0000:0x1300]` — wrapper plus TLV. Neither is the right range. The correct
range starts at the program header's `off`, not at zero, and ends at `off + filesz`.

I never derived the candidate list from the program headers. I guessed at round-number
boundaries instead of reading the structures that define the boundaries. Then I
reported the absence of a match as if the search had been exhaustive.

### What makes this the same failure as the rest

- **`0x23`:** interpreted a vendor NAK as a signature failure, because the first
  plausible explanation fit.
- **Zombie window:** treated PnP presence as evidence of a live endpoint.
- **Switch packet:** twice asserted a byte count from whichever source file I had open.
- **This one:** reported "not found" from a search that was not designed to find it.

The common shape is *concluding from an incomplete test and presenting the conclusion
at the same confidence as the measurement*. The fix is not more caution in wording; it
is deriving the test cases from the data structure rather than from memory.

### Correct statement, now in the docs

> The wrapper carries a SHA-512 over its own 4096-byte `ph[0]` payload (tag `0x8441`),
> verified byte for byte. **No per-image digest of the five inner images exists
> anywhere in the file**, tested against 9 algorithms and 84 candidate regions
> (`scripts/hash_sweep.py`).

The second sentence is now supported by a systematic sweep rather than a guess, and it
is reproducible. The first sentence replaced a claim that was simply false.

### One consequence worth keeping

Because the blob hashes the *wrapper*, and the wrapper is identical across builds, the
blob must be identical across builds too. That is consistent with the cross-build
finding in correction 2 — and it means the two observations reinforce each other
rather than being independent. An earlier draft of this entry presented them as two
separate pieces of evidence. They are one.

---

## Net effect on the repository

| Document | Change |
|---|---|
| `docs/04-melf-format.md` §2 | wrapper interior described correctly: the `0x1074..0x1300` region is a TLV, not padding |
| `docs/04-melf-format.md` §5 | "no hash table" replaced with the measured statement, plus the cross-build evidence |
| `docs/00-glossary.md` | TLV entry added; `goodix_ts` vs `goodixfp64` unaffected |
| `docs/14-edl-mode-switch.md` | unchanged — the 12-byte switch was correct |
| `scripts/find_hashes.py` | dissects the wrapper region by region and prints the TLV walk |

Nothing in the device conclusions changed. The repair is still two 1 MiB writes, and
the write blocker is still that Firehose never comes up.
