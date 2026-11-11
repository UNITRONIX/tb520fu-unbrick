# FEDL entry condition: one specific bit, read from the USB PHY status block

The chain from `boot_fedl_check` down to the decision is now complete, and it
reduces to a single masked comparison. This is the most concrete statement about
the hardware route that can be made without touching the device.

---

    10|## 1. The chain

```
[stage 1] boot_fedl_check @ 0x14843a7c
     |
     +-- bl 0x148507ec
     +-- bl 0x148509d4                    <- the decision
              |
              +-- bl 0x14850a98           <- read the USB status word
              |        |
              |        +-- adrp 0x148f5000 / ldrb [x8,#0x3e8]
              |        |     if != 1 -> bl 0x14850a8c  (read a live register)
              |        |     if == 1 -> ldrb [x8,#0x3ec] (use a cached value)
              |
              +-- and  w8, w0, #0x30000
              +-- cmp  w8, #0x10000
              +-- csinc w0, wzr, wzr, eq      w0 = 1 iff (status & 0x30000) == 0x10000
```

## 2. What the comparison means

`0x30000` masks bits 16 and 17. The `cmp` against `0x10000` and the `eq` means:

| bits 17:16 | result |
|---|---|
| `00` | 0 - no forced download |
| **`01` (`0x10000`)** | **1 - forced download requested** |
| `10` | 0 - a different state, explicitly not FEDL |
| `11` | 0 - likewise |

So FEDL is entered when **bit 16 is set and bit 17 is clear**, and nothing else
in that field matters. Notably `10` is *also* rejected - the check is not "any
USB activity", it is one specific encoded state.

## 3. Where the status word comes from

`0x14850a98` reads one of two places:

```
0x14850968   adrp x8, 0x148f5000
0x14850974   ldrb w8, [x8, #0x3e8]     a flag in RAM
0x14850978   cmp  w8, #0x1
0x1485097c   b.ne 0x1485098c           flag != 1 -> 0x14850a8c
0x14850980   adrp x8, 0x148f5000
0x14850984   ldrb w8, [x8, #0x3ec]     a cached value
```

and `0x14850a8c` builds the address `0x221C8604` - the USB PHY status register,
one 16-bit halfword after the latch at `0x221C8600` that the transport selector
(`0x148818cc`) reads.

So the two functions read **adjacent halfwords of the same PHY block**:

```
0x221C8600   read by 0x148818cc   -> chooses the EDL transport (USB vs PCIe)
0x221C8604   read by 0x14850a98   -> reports whether D+ ground is detected
```

That is coherent: one halfword says "we are in USB download mode", the other says
"the D+ condition was seen".

There is also a table at `0x14850a18` indexed by a small integer (0..3) selecting
between `0x221C8780`, `0x221C8604`, `0x221C8608`, `0x221C860C`, plus a read of
`0x1FD4000 + n`. So this is a generic USB-PHY register-access helper, not a
one-off.

## 4. What this changes about the procedure

**The check is not a poll and has no duration.** It reads a status bit. The
`check_dp_timeout = 10000` in the DCB therefore belongs to the *other* stage,
`boot_dload_handle_forced_dload_timeout`, which runs after this one.

That makes the physical requirement simpler and stricter at the same time:

- simpler, because there is no microsecond window to hit;
- stricter, because the bit has to be **already latched** when stage 1 reads it,
  which means the short must be in place before the PHY is initialised - i.e.
  before and during power-on, not after.

This is consistent with the "worked once" result: the one success was presumably
a moment when the short was genuinely present at PHY init.

## 5. Honest limits

- **Which physical pads to short is not established.** `docs/18` says the trigger
  is on the USB connector, and the firmware calls it "D+" ground, but no document
  here records a verified pin-out for this tablet's Type-C receptacle.
- **Bit 16 of `0x221C8604` is inferred** to mean "D+ ground detected" from the
  name of the caller (`boot_fedl_check`) and from `docs/18`'s reading of the
  strings. It is not read from a register description.
- **The latch persistence is unknown.** Whether a short applied during one boot
  survives into the next is untested.
- **Nothing here has been exercised on the device.** Every statement above is
  static reading of the image.

The value of the chain is that it turns "hold D+ low, maybe" into: *make bit 16
of the PHY status word set by the time stage 1 runs*. That is testable the moment
there is a way to observe the result, and the observation is a single one:
`tablet.py status` reporting `PID_9008`.

## 6. Reproduce

```
python scripts/tablet.py status                      # current mode
python scripts/tablet.py wait --want 9008 --seconds 120
```

Offline, the chain is in `find_fedl.py` and the addresses above; image[2] offsets
are `va - 0x14825000 + 0x1000`.
