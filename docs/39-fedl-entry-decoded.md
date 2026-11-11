# FEDL: the entry decision, decoded from the image

Goal: `HELLO ver=3 mode=0` from PBL. This document is about the hardware route,
because it is the only one that does not need the firmware to emit a HELLO first.

Everything below is read from `xbl_s_devprg_ns.melf`, with the segment arithmetic
checked against a known-good predicate. No device access was needed.

---

    10|## 1. The configuration the device declares

From `xbl_config.elf`, the **pre-ddr DTB of this board** (offset `0x13b30`,
length `0x11e2c`) — not from the programmer's copy:

```
/sw/boot/forced_download/feature          = 1        ENABLED
/sw/boot/forced_download/check_usb_option = 1        the USB check runs
/sw/boot/forced_download/check_dp_timeout = 0x2710   = 10000
/sw/boot/forced_download/ignore_pwr_key   = 0        power key matters
/sw/boot/fedl_timeout/ver                 = 1
/sw/boot/fedl_timeout/action              = 1
```

The important one is `check_dp_timeout = 10000`. `docs/18` reasoned the poll
window was ~50 ms from the disassembly of one loop. If 10000 is milliseconds, the
window is **ten seconds**, and the whole "hold the short before power-on" problem
stops being marginal. Settling this unit is the remaining open item.

## 2. The entry point

The string `"Enter PBL EDL USB"` is at VA `0x148aedab`, and its only code
reference is:

```
0x14843a04  adrp x8, 0x148ae000
0x14843a08  tst  w0, #0xff
0x14843a0c  add  x8, x8, #0xdab        "Enter PBL EDL USB"
0x14843a10  csel w22, w22, wzr, vs
0x14843a14  csel x19, x8, x19, cc      pick USB or PCIe message
0x14843a18  mov  x0, x19
0x14843a1c  orr  w21, w21, w22
0x14843a20  bl   0x1482a91c            log it
0x14843a24  strh w21, [x20]            write the TCSR
0x14843a28  bl   0x14840df0            <- EDL entry
0x14843a2c  movz w0, #0x1
0x14843a30  bl   0x1482e458
```

The sibling string at `0x148aed98` is `"Enter PBL EDL PCIe"`. So this function
chooses the EDL **transport**, and logs which one it took. `0x14840df0` is the
actual entry.

The surrounding function also:

```
0x148439c4  cbz x0, 0x14843a44        NULL context -> skip everything
0x148439c8  movz w1, #0x32
0x148439d0  bl 0x1482a210             read property 0x32
0x148439d8  movz w20, #0x9000
0x148439e0  movk w20, #0x1fd, lsl #16  w20 = 0x1FD9000   the TCSR block
0x148439ec  ldrh w8, [x20]            read it
0x148439f4  and w21, w8, #0xffffffc0  clear the low 6 bits
0x14843a00  bl 0x148818cc             <- the decision
0x14843a24  strh w21, [x20]           write back with new low bits
```

So the low 6 bits of `0x1FD9000` are the **download-mode stamp**, and bit 2 is
OR-ed in for the USB route. That is a persistent marker the next boot reads.

## 3. The decision function, and what it actually tests

`0x148818cc`:

```
0x148818cc  movz w8, #0x8600
0x148818d0  movk w8, #0x221c, lsl #16     w8 = 0x221C8600
0x148818d4  ldrh w8, [x8, #0x0]           16-bit read
0x148818d8  and  w8, w8, #0x3e
0x148818dc  cmp  w8, #0x6
0x148818e0  csel w0, wzr, wzr, eq         w0 = 1 iff (reg & 0x3e) == 6
0x148818e4  ret
```

This is **not** a read of the D+ line and it is not a timeout. It reads
`0x221C8600`, masks bits 1–5, and returns true when they equal `0b000110`.

`0x221C8600` is in the always-on / TCSR region, not in the USB PHY. The pattern —
mask, compare against a small constant, return 0/1 — is the shape of a **reset
reason / boot mode latch** test.

### What that means for the procedure

`docs/18` described the mechanism as a poll of the USB PHY with a ~50 ms window.
Three separate things in the image contradict that reading as a complete picture:

1. `check_dp_timeout = 10000` exists and is enabled, and nothing here is 50 ms.
2. The entry decision reads a **latched status register**, not the line itself.
3. The decision is made once and then **stamped into TCSR**, which is what a
   boot-to-boot handshake looks like.

The most consistent reading of the code: the D+ short is detected much earlier,
latched into `0x221C8600`, and this function reads the latch. That would make the
short's timing far less critical than `docs/18` concluded, and would mean the
"hold it before power-on" advice is right for a different reason than stated —
the latch has to be set by the time early boot reads it.

This is **inference, not measurement**, and is labelled as such.

## 4. What is still unknown, and it is now a short list

| question | how it would be settled |
|---|---|
| unit of `check_dp_timeout` (10000) | find the property consumer; the string is read indirectly |
| what `0x221C8600` bits 1–5 encode | needs a register description for this SoC, or two boots with different shorts |
| whether the latch persists across a power cycle | needs one successful short and a read of the register |
| whether `forced_download/feature=1` is enough by itself | test: hold D+ low, power on, watch for 9008 |

## 5. The procedure, as it now stands

Unchanged in its physical steps, but with a wider expected window:

```
1. power the tablet fully OFF
2. apply D+ held LOW on the USB connector
3. power ON with the short held
4. keep holding through boot
5. release once the device enumerates as 05C6:9008
```

Verification, in order of preference:

- `python scripts/tablet.py status` shows `PID_9008` instead of `PID_900E` —
  that alone is the success condition;
- `python scripts/tablet.py selftest` then reports `bytes pending` with
  `HELLO_REQ`, and the HELLO's version/mode can be read directly.

If `9008` appears, the state is exactly the one this session is aiming for:
**HELLO ver=3 mode=0, straight from PBL**, and it is the state in which a
programmer can be uploaded.
