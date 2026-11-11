# The FEDL decision, timed from the device's own log

`docs/39` and `docs/41` decoded the FEDL entry condition statically, from the image. This
document adds the timing, and the timing changes what the physical procedure has to be.

---

## 1. The sequence, from the log

The XBL log in the 40 MiB capture carries absolute timestamps (`B` lines are "since boot",
`D` lines are deltas). Reconstructing them gives the order of the USB stages on a real boot:

```
    215.208 ms   usb: usb_eud_serial , 0x147d8aa5
    599.874 ms   usb: qusb_dci_eud_init
    600.819 ms   usb: usb_hs_phy_cfg size , 0x20
    800.716 ms   usb: usb_dp_toggled_for_cdp , 0xc8
   1036.451 ms   boot_fedl_check                     <- D 396 us
   1036.451 ms   boot_dload_handle_forced_dload_timeout
```

Read in that order, three things become clear:

**a. `boot_fedl_check` runs ~1.04 s after power-on**, not in the first 50 ms. `docs/18`
concluded a ~50 ms window from a loop count; `docs/39` corrected that to "a latched status
read, no duration". The log settles it in favour of the correction **and** gives the actual
position: just after PHY configuration and just after the firmware's own D+ toggle.

**b. `usb_dp_toggled_for_cdp` at 800 ms comes BEFORE the check at 1036 ms.** `docs/79`
decoded that toggle as the firmware driving D+ for 200 ms and then flipping it. So by the
time `boot_fedl_check` reads the latch, the firmware has already been manipulating the line
itself for a quarter of a second. That is the mechanism by which a short applied *after*
power-on can be missed: the firmware's own toggle is the last thing that touched D+.

**c. `boot_dload_handle_forced_dload_timeout` runs immediately after the check**, with a
delta of 0 us. `docs/41` §4 said `check_dp_timeout = 10000` belongs to this stage and not to
the check; the log is consistent with that - the check itself measured 396 us.

## 2. What the conditions were on that boot

```
S - Boot Config @ 0x221c8600 = 0x00000001
```

The decision function masks bits 1-5 and requires `0b000110` (6):

```
(0x00000001 >> 1) & 0x1F  ==  0     ->  FEDL condition FALSE
```

So on the one boot that reached EDL, the FEDL path was **not** what took it there -
`boot_dload_entry` was reached through the cookie/counter path instead. The two routes are
genuinely independent, which matters: it means route (b) has never been exercised on this
unit, so its failure has never been observed either.

Every other recorded boot shows the same `0x00000001`. `scripts/fedl_latch.py` checks this
across captures and evaluates the condition:

```
DDRCS0_0_first40MB.bin: 2 boot log(s)
  BootConfig=0x00000001  bits1..5=0b00000 (0)  FEDL condition (==0b000110): false
  BootConfig=0x00000001  bits1..5=0b00000 (0)  FEDL condition (==0b000110): false
DDRCS0_0_first28MB.bin: 1 boot log(s)
  BootConfig=0x00000001  bits1..5=0b00000 (0)  FEDL condition (==0b000110): false
```

## 3. The consequence for the physical attempt

The short must be present when the PHY is configured at **~600 ms**, and must survive the
firmware's own toggle at **~800 ms** so that the latch reads true at **~1036 ms**. Practically:

```
1. apply the short with the device OFF and the cable already in the PC
2. then power on, with the short held
3. keep holding through at least the first 1.5 s of boot
4. release
```

The "hold 5 s then release" from `docs/93` is compatible but tighter than it needs to be;
what it must not be is "plug in and then short", because at 600-1036 ms the window has
already passed.

**And the attempt is now diagnosable even when it fails.** If a fresh capture after the
attempt shows `BootConfig` bits 1-5 == 6, the short was seen and something downstream
blocked EDL. If it still reads `0x00000001`, the short was not seen at all and the
electrical setup is wrong - two completely different next steps that previously looked
identical from the host.

## 4. What this does not settle

- **The pad/pin question is still open.** Nothing here identifies which contacts to short
  on this tablet's Type-C receptacle; `docs/93` §2 covers the two-pair problem.
- **Whether the short can latch at all** on this unit is untested. `docs/39` labels the
  latch-persistence question as unknown, and it stays unknown until an attempt is made.
- The 396 us figure is what the *log line* measured, not the whole decision path; it says
  the check is cheap, not that it reads only one register.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.**

New: the FEDL decision has a measured position on the boot timeline (~1.04 s, after the
firmware's own D+ toggle at ~0.80 s), and its condition is now readable from any capture -
so route (b) can be attempted with a result that distinguishes "short not seen" from
"short seen but EDL blocked".
