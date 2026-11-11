# CD_STRCT is live ARM64 code, and it reads the same USB PHY status block

`crash_region_probe/sample_0x0080000000_CD_STRCT.BIN.bin` is one of the
crash-context regions (`docs/15` §2 lists it as "crash structure"). It is 488
bytes. It is **not a data structure** - it is executable ARM64 that runs at
`0x80000000` in the crash path, and it touches the same registers that decide the
FEDL and EUD routes.

---

    10|## 1. It is code

Decoded at base `0x80000000`, the first instructions are a coherent startup
sequence:

```
0x80000000  movz x10, #0x1800
0x80000004  movk x10, #0x3040, lsl #16
0x80000008  msr  s3_4_c1_c0_0, x10        a system register write
0x80000010  adr  x1, 0x800df278
0x80000014  str  x0, [x1]                 save the incoming argument
0x80000018  movz x11, #0x8004
0x8000001c  movk x11, #0x1fc, lsl #16     x11 = 0x1FC8004
0x80000020  ldrh w10, [x11]               read a halfword
0x80000024  and  w10, w10, #0x7           mask three bits
0x80000030  strh w10, [x9]                store it
0x8000003c  cmp  w10, #0
0x80000040  b.ne 0x80000050
0x80000044  ldrh w0, [x18, #0x4]          x18 = 0x10CC000
0x80000048  ands w0, w0, #1
0x8000004c  b.eq 0x800000d4               bit clear -> the hang path
```

`0x800000d4` is followed by `0x800000d8  b 0x800000d4` - an **infinite loop**.
That is the same shape `docs/20` found in the Firehose entry stub: a self-branch
used as a deliberate stop.

## 2. The registers it reads

```
x11 = 0x1FC8004      a TCSR-adjacent block, 3 bits masked and saved
x18 = 0x10CC000      read at +0x4, bit 0
then, later in the same function:
x11 = 0x221C8000     read at +0x610, +0x700, +0x744
```

`0x221C8xxx` is the block that decides FEDL (`0x221C8604`, `docs/41`) and EUD
(`0x088E2000` is the PHY, and `docs\45` showed the port-select lives in the same
region). So the crash path and the download-entry path consult **the same
halfword region**, at different offsets:

```
0x221C8600   transport selection        (docs/41 s3)
0x221C8604   D+ condition latch          (docs/41 s2)
0x221C8610   read here in the crash path
0x221C8700   read here
0x221C8744   read here
```

Each value is read, then stored to a fixed address near `0x800DF408`:

```
0x800000b8  adr  x9, 0x800df40c
0x800000bc  strh w10, [x9]        -> 0x800DF40C gets [0x221C8700]
0x800000c8  adr  x9, 0x800df408
0x800000cc  strh w10, [x9]        -> 0x800DF408 gets [0x221C8744]
```

So the crash handler **snapshots three USB-PHY halfwords into a fixed table
before it halts**. That table is at `0x800DF408`–`0x800DF414`, which is inside the
exposed `DDRCS0_0` window and therefore **readable from the host**.

## 3. Why this matters for the goal

If those three halfwords were captured at the moment of the crash, then the
device's own record of the USB PHY state at the failure is already sitting in
memory we can read - and it is the same state the FEDL/EUD decisions depend on.

That is worth checking before any further physical attempt, because it could
settle, from data:

- whether the D+ condition latch was ever set;
- which transport state the crash path observed;
- whether the crash and the download-entry path are looking at the same thing.

The addresses to read are `0x800DF408`, `0x800DF40C`, `0x800DF410` - three
halfwords inside the already-exposed first DDR window.

**This has not been read yet.** Reading it needs a fresh HELLO, which is the
blocker the whole session has been fighting. It is recorded here because it is a
concrete, small, high-value read the moment route A or B succeeds - three bytes,
not a multi-gigabyte sweep.

## 4. What is not claimed

- The decoding above is static. The self-loop at `0x800000d4` is read as "stop",
  by analogy with `docs/20`, not from a proven convention.
- The three stored values are shown to come from `0x221C8xxx`; it is **not**
  established which halfword is which, beyond the offsets.
- Whether this code runs on this unit's crashes, or is a path for a different
  fault class, is not established. It sits in the region the crash dump exposes as
  `CD_STRCT`, which is suggestive and not proof.
