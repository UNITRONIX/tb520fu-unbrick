# The download request is bit 12 of the TCSR cookie register

`docs/68` left one question: what set the download request on the boot that reached
EDL. The read path has now been decoded, and it is a single bit test.

---

## 1. The function at `0x14843a90`

```
0x14843a90  movz w9, #0x9000
0x14843a94  movk w9, #0x1fd, lsl #16     w9 = 0x1FD9000    the cookie register
0x14843a98  str  sp, [x29, #0x18]
0x14843a9c  str  sp, [x29, #-0x8]
0x14843aa0  str  x8, [sp, #0x0]
0x14843aa4  ldrh w8, [x9, #0x0]          read the cookie halfword
0x14843aa8  tbnz x8, #12, 0x14843ab4     test BIT 12
0x14843aac  mov  w0, wzr
0x14843ab0  b    0x14843b64             bit clear -> return 0, no request
0x14843ab4  ...                          bit set -> continue down the request path
0x14843ab8  add  x2, x29, #0x18
0x14843ac0  bl   0x1482a144             read property 0x15
0x14843ad4  sub  x2, x29, #0x8
0x14843adc  bl   0x1482a144             read property 0x14
0x14843af4  add  x2, x2, #0xdbd         "Enter PBL EDL ..." family
0x14843afc  bl   0x1484e3b8             look up a DTB node
```

**The gate is bit 12** (`0x1000`) of the halfword at `0x1FD9000`.

## 2. Reconciling with `uefiplat.cfg`

`docs/65` recorded the vendor's config:

```
DloadCookieAddr = 0x01FD9000
# for full dump 0x10, for minidump 0x20
DloadCookieValue = 0x10
```

`0x10` sets bit 4, not bit 12. So these are **two different things in the same
register**:

| bits | meaning | source |
|---|---|---|
| bit 12 (`0x1000`) | download requested - the gate decoded above | XBL code |
| bit 4 (`0x10`) | dump *mode*: full dump | `uefiplat.cfg` comment |

That is consistent, not contradictory: one bit says *"a dump was requested"*, another
field says *"when requested, make it a full dump rather than a minidump"*. The log
line `TCSR reg value 0x10` in the working boot is therefore reporting the **mode**
field, and by itself does not prove bit 12 was set - the boot could have had both.

**This is a correction to `docs/58`'s reading**, which treated `TCSR reg value 0x10`
as if it were the request itself. It is the mode; the request is bit 12.

## 3. Why the 16-bit read matters

The code does `ldrh` - a 16-bit read - and tests bit 12 of that halfword. So the
request lives in the low 16 bits of `0x1FD9000`, which is the same halfword
`docs/40`/`61` called "bits `0x30`" (bits 4 and 5) for the DDR-training guard.

Those are different bits of the same halfword, which explains why several documents
kept colliding on this register:

```
0x1FD9000 low halfword
  bit 4   (0x0010)  dump mode = full dump          uefiplat.cfg
  bit 5   (0x0020)  dump mode = minidump           uefiplat.cfg comment
  bits 4+5 (0x0030) DDR training guard             docs/16 s5, docs/40
  bit 12  (0x1000)  download requested             this document
  low 6 bits        route stamp written by crash handler   docs/61
```

> **RESOLVED (same session).** The apparent conflict is not one. All five functions
> that touch `0x1FD9000` were read together:
>
> ```
> 0x1484396c  ldrh ; tst #0x30 ; csinc        READS bits 4+5
> 0x14843984  ldrh ; orr #0x10 ; strh         WRITES bit 4
> 0x14843998  ldrh ; orr #0x20 ; strh         WRITES bit 5
> 0x1484383c  ldrh ; and #0x30 ; ret          RETURNS bits 4+5
> 0x14843a90  ldrh ; tbnz #12                 READS bit 12
> ```
>
> Bits 4 and 5 are a **two-bit field**: `0x10` = full dump, `0x20` = minidump,
> written by the two setters and read as a field by the two getters. `docs/16`
> called the getter "the DDR training guard" and `uefiplat.cfg` calls the field
> "dump mode" - **both describe the same field from different ends**. There is no
> contradiction, only a name that was assigned before the writer was found.
>
> Bit 12 is separate: it says *a* dump was requested, while bits 4/5 say *which
> kind*.
>
> The earlier paragraph is kept because the reasoning that produced the "conflict"
> is itself instructive: two documents named one field differently and neither had
> seen the setters.

## 4. What this gives the goal

The download request is now a **named bit at a named address**:

```
[0x1FD9000] bit 12 = 1   ->  XBL takes the download path -> boot_dload_entry -> EDL
```

That is a concrete target, and it is in the always-on TCSR block - which survives a
reset and is not re-initialised by a cold boot. That is why a boot could read a
request set by an earlier one (`docs/68` §4).

## 5. What is still open

- **Who sets bit 12.** The reader is decoded; the writer is not. `uefiplat.cfg`
  writes the mode value, and the crash handler stamps the low six bits
  (`docs/61`), but neither is shown to set bit 12.
- **Whether bit 12 can be set from the host.** It is a TCSR register; without a
  Sahara session or a JTAG path, no.
- **The bits 4/5 contradiction** in §3.
- Whether bit 12 is currently set on this unit - which would need a session to read,
  the standing blocker.

**The actionable consequence is unchanged and now better aimed**: get bit 12 set, and
the next XBL boot enters EDL without needing UEFI, ABL or a handoff (`docs/68`).
