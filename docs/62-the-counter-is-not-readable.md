# The counter is real but not readable — and that constrains what can be verified

`docs/59` and `docs/61` reduced the EDL decision to one variable:
`dload_entry_count` at `0x148F0080`. This document records where that address
actually lives and what that means for verification.

---

    10|## 1. Where `0x148F0080` is

The crash-dump memory table exposes nine regions. Checking each against the target:

```
region          base            size        contains 0x148F0080?
OCIMEM          0x14680000      0x2C000     no  (ends 0x146AC000)
CODERAM         0x0B000000      0x18000     no
DATARAM         0x0B0E0000      0x8000      no
MSGRAM0..15     0x0C310000..    0x400 each   no
SHRM_MEM        0x24020000      0x40000     no
DCC_SRAM        0x10080000      0x18000     no
DCC_CFG         0x100FF000      0x1000      no
sbl_pmic_dump   0x1000000000    0x80000     no
DDR_DATA        0x1000080000    0x40000     no
```

Nearest region ending below it is OCIMEM, which stops `0x244080` short. The DDR
capture we hold covers `0x80000000`–`0x82800000`, so it does not reach it either.

**So the counter is in a block the crash handler does not expose.** That is a
concrete blocker, not an inconvenience - the one variable the whole analysis
reduced to cannot be read with the tooling that exists.

## 2. What *is* resident in the dump

Searching the 40 MiB DDR capture for the relevant identifiers:

```
skip_ddr_init_in_EDL     1 occurrence   at 0x81A13C43
boot_fedl_check          2 occurrences  at 0x81A0163D, 0x81CE5502
/sw/boot                 2 occurrences  at 0x81AD4399, 0x81AD5F5D
dload_entry_count        0 occurrences
```

Two useful observations:

- **`dload_entry_count` appears nowhere in the dump**, which is consistent with the
  counter *message* never having been logged - `docs/59` §4 used that absence to
  conclude the working boot was a first entry. This is a second, independent search
  confirming the same thing from the string side.
- **`skip_ddr_init_in_EDL` does appear once**, at `0x81A13C43` - the copy inside the
  resident XBL code. So the property *name* is in memory even though the property
  *value* lives in the non-exposed block.

## 3. The consequence for the goal

The chain is now:

```
gate 1   lazy initialiser                     passes, not a gate        (docs/61)
gate 2   skip_ddr_init_in_EDL = 0 < 2         passes, deterministic     (docs/60)
gate 3   dload_entry_count >= 2               the only variable         (docs/59)
```

and gate 3's state **cannot be observed** with the available tooling:

| what would settle it | why it is unavailable |
|---|---|
| read `0x148F0080` | not in any exposed region |
| read it live over Sahara | needs a HELLO, which is the blocker |
| infer it from the log | only the *absence* of the message is observable, and only while the log ring has not wrapped |

That third row is what was used, and it is weak: the log ring is small
(`docs/51` showed `PMON_HIS` wrapping), so "the message is absent" could mean
either "it never happened" or "it was overwritten".

## 4. What this leaves as genuinely actionable

The analysis has done what analysis can do. What remains are physical facts, and
they should be attempted in the order of how much each would teach:

    60|1. **A genuine cold boot, powered on once, no warm reset.** If the counter is the
   gate, this is the only thing that clears it. Verification is immediate:
   `tablet.py status` showing `PID_9008`, or `selftest` reporting bytes pending.
2. **Check the battery.** `docs/57` recorded `VBAT 3588mV` and `UFS Gear 1 due to
   low battery` on both logged boots. Charging is zero-risk and removes a measured
   degradation that has confused this project before (`docs/07` §E1).
3. **The vendor procedure from a verified off state** (`docs/43`, `docs/51`),
   with `scripts/vendor_entry.py`.

All three are free, none require opening the case, and each produces a definite
answer rather than another inference.

## 5. Honest summary of where the goal stands

The goal is `HELLO ver=3 mode=0` from PBL. It has **not** been achieved. What the
session produced is a precise account of what stands in the way:

- the hardware is not faulty - training covers 8 x 2 GiB (`docs/36`), the 40 MiB
  boundary is a region boundary (`docs/46`), and XBL runs to completion and loads
  APPSBL (`docs/56`);
- the download path exists, is cheap, and was **reached once** (`docs/58`);
- one counter gates it (`docs/59`), that counter is not readable (`this document`),
  and the only way past it is a cold boot with no warm reset before the attempt.

That is a testable hypothesis with a one-step physical test, not an open-ended
problem.
