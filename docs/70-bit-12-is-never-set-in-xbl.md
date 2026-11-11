# Bit 12 is never set inside XBL — the setter is elsewhere

`docs/69` found that bit 12 of `0x1FD9000` is what XBL tests for a download request,
and left "who sets it" open. A complete enumeration of the register's use answers it
by elimination.

---

## 1. Every reference to the cookie register, exhaustively

Searching all of image[2] for the exact `movz #0x9000` + `movk #0x1fd` pair:

```
0x1484383c   w8/w8    ldrh ; and #0x30 ; ret        READ bits 4+5
0x148438f4   w9/w9    (part of the 0x14843900 block)  READ
0x1484396c   w8/w8    ldrh ; tst #0x30 ; csinc        READ bits 4+5
0x14843984   w8/w8    ldrh ; orr #0x10 ; strh         WRITE bit 4
0x14843998   w8/w8    ldrh ; orr #0x20 ; strh         WRITE bit 5
0x14843a90   w9/w9    ldrh ; tbnz #12                 READ bit 12
```

**Six sites. Not one of them sets bit 12.**

> **Method note.** An earlier pass of this search returned zero hits because the
> `movk` mask was written as `0x72A00000` instead of `0x72800000`. That masked a
> whole class of instructions and produced two rounds of empty results, which were
> briefly read as "the setter does not exist" before the encoding was checked
> against a known instruction at `0x1f96c`. The check is recorded because "empty
> result" and "wrong filter" look identical, and this project has been bitten by
> that distinction repeatedly (`docs/32` rule 3).

## 2. What the six sites do

| bits | operation | direction |
|---|---|---|
| 4 | full dump | written by `0x14843984` |
| 5 | minidump | written by `0x14843998` |
| 4+5 | dump-mode field | read by `0x1484383c`, `0x1484396c` |
| 12 | download request | **read only** by `0x14843a90` |

So XBL:
- **decides** which dump to take (bits 4/5),
- **honours** a request (bit 12),
- and **cannot make** a request itself.

## 3. What that means

The download request must be written by something that is not the XBL in this melf.
The candidates, in the order the evidence supports:

1. **The stock bootloader chain**, before the brick - the cookie lives in TCSR, in the
   always-on domain, so a value written months ago could still be there (`docs/68` §4).
2. **PBL**, which runs before XBL and has its own view of the same TCSR block.
3. **TrustZone**, which `docs/66` showed is the only path that can write this register
   from the AP side (`TZ_IO_ACCESS_WRITE_ID`).

The third is the most interesting, because `docs/66` found the write going through
TZ - and TZ code is in `tz.mbn`, which is in the ROM package and has **not** been
examined.

## 4. The next bounded question

`tz.mbn` is 4 137 440 bytes and sits in `com_attempt/image`. Searching it for the
cookie address is a bounded, mechanical step - the same method that has worked all
session: find the constant, find its code, read the branch.

That is the only remaining place a writer can be, given §1.

## 5. Status

Goal unchanged: `HELLO ver=3 mode=0` not obtained.

What this document establishes is a **negative that narrows the search to one file**:
the request bit cannot be set by XBL, so it is set by code that runs before XBL (PBL)
or alongside it through a secure call (TZ). Since PBL is in ROM and unreadable, `tz.mbn`
is the only readable candidate.
