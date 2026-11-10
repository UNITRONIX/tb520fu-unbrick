# The write gate: it is a byte, not a fuse

**This document records the most consequential finding of the project.** It
replaces the assumption that write access to this tablet is refused by hardware.

---

## 1. What was assumed, and why it was wrong

Every previous plan — the service report, the board-swap quote, the test-point
argument — rested on one premise: *writing to this tablet's storage is not possible
from the host*.

That premise was never tested. It was inferred from the fact that Firehose never
comes up. But "Firehose does not run" and "the device would refuse to write if it
did run" are different statements, and only the first was ever measured.

Checking the second gives a different answer.

---

## 2. The programmer is not crippled

`scripts/firehose_capability_scan.py` over image [3] of the melf — which is
bit-identical to `prog_firehose_ddr.elf`:

```
configure             negotiate transfer params
read              x22 READ from storage
program            x1 WRITE to storage
erase             x10 ERASE storage
patch              x3 apply raw memory patches
power              x4 power off / reset
peek               x1 read memory
poke               x1 write memory
getstorageinfo     x1 storage geometry
setbootablestorage x1 set boot LUN
getsha256digest    x1 digest of a region
```

plus the `<data>` element the XML transport uses.

The full write path exists: `program`, `erase`, `patch`, `poke`. So the tooling was
never the obstacle. The obstacle is a **decision** the programmer makes before
using that path.

---

## 3. The decision, located and decoded

Two independent call sites gate writing and erasing, and both use the same
predicate:

```
write path   (image+0x8ea0)          erase path (image+0x9ac0)
  bl 0x149a369c                        bl 0x149a369c
  cmp w0, #0x1                         cmp w0, #0x1
  b.ne allow                           b.ne allow
  "device is locked, cannot write"     "device is locked, cannot erase"
```

So: **`w0 == 1` means locked; anything else means permitted.**

The predicate is at va `0x149a369c` = image+0xb69c, and it is a real function entry
(`sub sp, sp, #0x50`). Its body:

```
0xb6c0  bl 0x149a896c              setup
0xb6c4  cbz w0, 0xb700             w0 == 0 -> go read the partition
0xb6c8  ...
0xb6e0  bl 0x149a4df0              attempt the partition read
0xb6e4  cbz w0, 0xb700             read OK -> compare the byte
0xb6e8  bl 0x149a3850
0xb6ec  "read_lock_partition: fail to read lenovo lock partition"
0xb6fc  b 0xb72c
...
0xb700  ...
0xb744  ldrb w8, [sp, #0x20]       the byte, read from the partition
0xb748  cmp  w8, #0x1
0xb74c  1a9f17e0                   csinc w0, wzr, wzr, NE
0xb750  b 0xb730
...
0xb72c  mov w0, wzr                <- the read-failure return
```

### The byte

`0x1a9f17e0` decoded by field, not by name:

```
sf=0  op=0  S=0  11010100  Rm=11111(wzr)  cond=0001(NE)  op2=01  Rn=11111(wzr)  Rd=w0
                                        -> CSINC w0, wzr, wzr, NE
```

`CSINC` returns `Rn` when the condition holds and `Rn + 1` otherwise:

| lock byte | NE after `cmp w8,#1` | w0 | caller verdict |
|---|---|---|---|
| **1** | false | **1** | `w0 == 1` → **LOCKED** |
| 0 | true | 0 | `w0 != 1` → write allowed |
| 2..255 | true | 0 | `w0 != 1` → write allowed |

The lock byte must be **exactly 1**. No other value locks the device.

### The failure path

```
0xb6e4  cbz w0, 0xb700     read succeeded -> compare
0xb6fc  b 0xb72c           read FAILED
0xb72c  mov w0, wzr        return 0
```

A failed read returns **0**, which the caller reads as *permitted*. The gate is
**fail-open**: if the lock partition cannot be read, the device is treated as
unlocked.

---

## 4. The partition exists, and where it is

The string names the artefact, and the GPT confirms it. From `gpt_main0.bin`
(LUN 0, header at `0x1000`, entries at `0x2000`, 32 × 128 B):

```
lenovolock    first sector 774   last 901   128 sectors   524 288 B (512 KiB)
lenovocust    first sector 902   last 77701
lenovoraw     first sector 77702 last 81797
```

So the lock state lives in a **512 KiB partition named `lenovolock` on LUN 0**, at
byte offset `774 × 4096 = 3 170 304`.

The predicate reads a byte out of it (`ldrb w8, [sp, #0x20]` after the read
completes) and locks the device when that byte is exactly `1`.

---

## 5. Where the read goes, and what is *not* gated

Tracing `0x149a4df0` (the raw partition reader) shows seven call sites:

```
0x149a0840   0x149a1198   0x149a1458   0x149a1670
0x149a276c   0x149a36e0   0x149a3b24
```

The one at `0x149a0840` is a **hashing/digest path**, not a gate:

```
0x8840  bl 0x149a4df0
0x8844  strh w0, [sp, #0x14]
0x8848  cbnz w0, 0x149a089c
...
0x8884  "Can't open sha256 handle %d"
0x889c  "Failed to read data for hashing, sector %ld count %ld, error ..."
```

And the lock predicate itself has exactly **two** callers:

```
0x149a0ea0    the write path      -> "device is locked, cannot write"
0x149a1ac0    the erase path      -> "device is locked, cannot erase"
```

Nothing else consults it.

**Consequence:** the lock does not gate `configure`, `read`, `getstorageinfo`,
`peek` or digest operations. A locked device still accepts a full read session and
still reports its geometry. Only storage *mutation* is refused.

That matters practically: if the XML listener ever comes up, a locked tablet is
still fully inspectable. Reading `lenovolock` to learn its actual byte, dumping
partitions to verify state, and confirming the storage geometry — all of it works
without touching the lock.

---

## 6. What this means

Three statements, each measured rather than inferred:

1. **The lock state is data on UFS.** The error string names the operation:
   `read_lock_partition: fail to read lenovo lock partition`. It reads a partition.
   It does not read a fuse, a register, or a signature.
2. **The condition is a single byte equal to 1.** Not a hash, not a certificate,
   not a secure-boot state.
3. **The absence of the data grants permission.** Fail-open.

This is a materially different situation from "the SoC refuses by design". A fuse
cannot be argued with; a partition lookup can be, in principle, in three distinct
ways:

- the byte is not 1 (or the partition is empty/unreadable),
- the lookup itself fails,
- the code never reaches the check because Firehose never runs.

Note the ordering: the third is the *current* blocker and the one that matters
today. The first two describe what happens once the programmer does run.

---

## 7. What is still not established

Being explicit, because the previous sections of this project suffered from
conclusions that ran ahead of evidence:

- **The current value of the lock byte on this tablet.** Unknown. The partition is
  identified (`lenovolock`, LUN 0, sectors 774–901), but reading it needs either a
  working Firehose session or a way to reach that LUN from the crash dump — and the
  crash dump does not expose UFS at all.
- **Whether the gate is reached at all today.** It is not: the programmer never
  raises its XML listener. Every finding here is about what happens *after* that
  problem is solved.
- **Whether other checks exist downstream.** `bProvisioningType`, `UFS Provisioning
  Type`, VIP authentication and `No configuration/provisioning allowed for this
  device type` all appear in the image and may add conditions to specific
  operations. Only the write/erase gate has been decoded.
- **Whether the 512 KiB partition contains other state that matters.** Only the
  single compared byte has been traced.

---

## 8. Where the effort should go

The gate analysis changes the priority order. Getting Firehose to run is not just
"the first step" — it is very likely the **only** remaining step, because the thing
that was believed to be the second wall turns out to be a byte with a fail-open
read.

The next question is therefore narrow and technical: *why does the programmer,
having been accepted by PBL with `END 0x00` and `DONE` acknowledged, never raise its
XML listener?* See `16-firehose-bringup.md` for the pipeline and the addresses.

### 8.1 The first action once the programmer speaks

Reading `lenovolock` needs no write permission, and the XML surface supports the
addressing:

```
physical_partition_number     supported  (image+0x36590)
start_sector                  supported  (image+0x36709)
num_partition_sectors         supported  (image+0x366cb)
SECTOR_SIZE_IN_BYTES          supported  (image+0x3668f)
byte_offset                   supported  (image+0x36a44)
```

So the target read is expressible directly, without depending on GPT parsing:

```
<read physical_partition_number="0"
      start_sector="774"
      num_partition_sectors="128"
      SECTOR_SIZE_IN_BYTES="4096" />
```

and then: read the first byte. `1` means locked; anything else means the write path
would be permitted. `scripts/xml_attribute_scan.py` reproduces the capability list.

### 8.2 What to do with each outcome

| lock byte | meaning | consequence |
|---|---|---|
| `1` | locked | writing is refused by a data byte; the question becomes how that byte came to be 1, and whether it can be cleared |
| not `1`, or read fails | permitted (fail-open) | the gate is already open and `program`/`erase` would be accepted |

Neither branch requires a board swap. Both require a running programmer.

---

## 9. Honest position

The write gate is decoded. That is progress on a question that had been assumed
settled in the wrong direction. It does **not** yet recover the tablet, and it would
be dishonest to imply otherwise:

- the programmer still does not run, and that is unchanged by anything here;
- the lock byte's current value is unknown;
- the fail-open behaviour is a property of the code, not a claim that this specific
  tablet's partition is unreadable;
- writing still requires the programmer, so no new write capability has been gained
  today.

What has changed is the *shape* of the remaining problem. It used to be: "cannot
write, therefore hardware intervention". It is now: "the programmer must start; if
it starts, the write path is available unless one byte says otherwise."

---

## 10. Method note

Two mistakes were made and caught during this analysis, and both are recorded
because they are the kind that produce confident nonsense:

- A disassembly was read from an address that was **not** a function entry
  (`0x149a369c` was initially treated as the caller's callee boundary), producing a
  coherent-looking but meaningless listing. Caught by `find_func_start.py`.
- An `ADRP` was annotated with its **page** instead of the final `ADRP+ADD`
  address, which printed the wrong string next to an instruction and made a
  plausible-looking match that was not one. Caught by re-resolving the pair.

Both are now mechanical checks in `audit_references.py` and `image_dump.py
--annotate`. The habit behind them is the one worth keeping: **a branch direction
and a resolved address are evidence; a name, a comment, or a plausible-looking
listing is not.**
