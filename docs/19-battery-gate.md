# The battery gate runs in XBL, before Firehose exists

This closes a gap that earlier documents left open, and it reopens a hypothesis that
`05-firehose-and-the-silence.md` had written off.

---

## 1. Why DBC deserves a second look

`05-firehose-and-the-silence.md` §6.2 proposed that the programmer's battery guard
could be shutting the device down, then dismissed it with this reasoning:

> A power-down produces an absence **without** a watchdog reset. What is observed is
> a watchdog reset.

That reasoning is sound but incomplete. It rules out a *clean* power-down. It does
**not** rule out the battery check **refusing to proceed** and leaving the CPU
stuck — which ends in exactly the observed trace: silence, then the watchdog.

The distinction matters because the two produce the same symptom but different
remedies.

So the question is: does such a refusal point exist, and can boot reach it before
USB comes up?

---

## 2. Where the battery code actually lives

`scripts/find_dbc_gate.py` searched both images for the DBC messages:

| message | image 2 (XBL core) | image 3 (Firehose) |
|---|---|---|
| `Loader dbc skipped` | present, `0x148ad54b` | **absent** |
| `battery recover failed` | present, `0x148ad522` | **absent** |
| `charger is not charging` | present (string only) | **absent** |
| `No battery` | present, `0x148ad6f5` | **absent** |
| `vsys-min-recover-mv` | present, `0x148ad0d5` | **absent** |
| `vbatt-min` | present, `0x148ad135` | **absent** |

**Every DBC string is in the XBL core and none is in Firehose.**

That is the structural fact that matters: the battery gate executes during XBL
initialisation, i.e. *before* the programmer is even reached. If a battery condition
can stop XBL, Firehose never gets the chance to fail — and the observed "silence
then watchdog" would be caused one layer earlier than anything previously
investigated.

---

## 3. The recovery loop, decoded

The function at `0x14837c7c` handles battery recovery. Its retry path:

```
0x14837f48  ldrh w8, [x21, #0xbc]      configured threshold, from the DT struct
0x14837f4c  movz w21, #0x86a0
0x14837f54  movk w21, #0x1, lsl #16    -> w21 = 0x186a0 = 100 000
0x14837f50  ldrh w9, [x29, #-0xc]      measured value
0x14837f58  sub  w22, w8, w9           difference
0x14837f60  tbnz x22, #31, ...         negative -> different path
```

and the retry itself:

```
0x14838008  "battery recover failed"
0x14838014  movz w0, #0x4240
0x14838018  movk w0, #0xf, lsl #16     -> 1 000 000
0x1483801c  bl 0x14832ac8              delay(1 000 000 us)  = ONE SECOND
0x14838020  bl 0x14832bcc              retry
0x14838028  "Battery recovered"
```

The delay helper is a thin wrapper over the same microsecond-based routine already
identified for the FEDL poll:

```
0x14832ac8  stp x29, x30, [sp, #-0x10]!
0x14832acc  add x29, sp, #0x0
0x14832ad0  bl 0x14847cd4              microsecond delay
0x14832ad4  mov w0, wzr
```

So the retry is **once per second**.

There is also an inner pacing loop, which *is* bounded:

```
0x14837ef4  ldrh w8, [x21, #0xa4]      count from the config struct
0x14837ef8  cmp  w24, w8
0x14837efc  b.cs 0x14837f34            exit when w24 >= count
0x14837f00  bl 0x14837b98
0x14837f14  mul  w0, w8, w23
0x14837f18  bl 0x14832ac8              delay(w8 * w23)
0x14837f28  add  w24, w24, #0x1f4      advance by 500
0x14837f30  b 0x14837ef4
```

---

## 4. What is established, and what is not

**Established:**

- the battery gate is in the XBL core, before Firehose;
- the retry cadence is one second;
- the inner pacing loop is bounded by a value from the configuration structure;
- the threshold compared is read from that structure at offset `0xbc`, not
  hard-coded.

**Not established:**

- whether the **outer** retry loop is bounded. The one-second delay plus a retry
  call is present, but the exit condition has not been isolated. An unbounded retry
  with a one-second delay is indistinguishable from a hang from the outside.
- the actual value in the PMIC registers on this unit at the moment the programmer
  runs. The crash dump exposes `PMIC_PON` but not a live VBAT reading.
- whether this unit's charger is detected. `boot-wo-batt = 1` in the device tree
  says the firmware is willing to boot without a battery, which reduces the
  likelihood that an absent battery is the blocker — but it says nothing about a
  *rejected* charger.

---

## 5. The configuration values that matter

From `/sw/pmic/pm/charger` in the DCB (`scripts/probe_policy.py`):

```
apply-boot-wo-batt     = 1        boot without battery is permitted
boot-wo-batt           = 1
icl-boot-wo-batt       = 1000 mA
vsysmin                = 2800 mV
float-voltage-mv       = 4350 mV
fast-charge-ma         = 500
skip-loader-dbc        = (empty)  DBC NOT skipped
skip-core-dbc          = (empty)  DBC NOT skipped
core-dbc-threshold     = 3200 mV
dbc-sdp-thd-inc        = 100
min-dbg-board-id       = 3000
max-dbg-board-id       = 11000
```

Two observations:

1. **`skip-loader-dbc` and `skip-core-dbc` are empty**, so the DBC is active. Setting
   either would bypass it — and this is a device-tree property, i.e. exactly the kind
   of thing that would need to be written to take effect.
2. `min-dbg-board-id = 3000` and `core-dbc-threshold = 3200` are suspiciously close,
   and `3000` also appeared as a constant in the recovery function. Whether they are
   independent or correlated has not been determined, and should not be assumed.

---

## 6. Why this is worth pursuing

The previous conclusion was that the failure sits in the programmer's runtime. That
may still be true, but this finding moves the plausible failure point **one layer
earlier**, into XBL, where the battery gate lives and where a refusal produces
precisely the signal we measure.

### The live-VBAT search, and why it failed

`scripts/find_live_vbat.py` scanned the two dump regions for 16-bit values in a
plausible single-cell range (3000–4600 mV):

```
sbl_pmic_dump   495 values in range, 255 clusters
SHRM_MEM       2823 values in range, 1486 clusters
```

**That is noise, not a measurement.** A 512 KiB region contains thousands of u16
values, so several hundred will inevitably fall in any 1600-wide window. The
most-common values (4112, 4352, 3072 in the PMIC dump; 4335, 4417, 4085 in SHRM)
are scattered across the file rather than confined to a register block, which is
what an ADC output would look like.

There was one superficially promising cluster in SHRM_MEM at `0x017b48`
(`4086, 4093, 4070, 4195, 4086, 4086, 4092, 4069...`) — tight, consistent values.
But consistency is not evidence of being a voltage; it is equally consistent with
any repeated data field, and the region is firmware data, not a PMIC capture.

**Conclusion: the dumps do not yield a live VBAT.** The measurement this hypothesis
needs cannot be obtained from what is on disk. It would require either a working
PMIC ADC read over EDL, or a physical measurement at the battery connector.

That is not a reason to discard the hypothesis — it is a reason to be explicit that
it remains untested rather than refuted.

---

## 7. Method note

Two earlier arithmetic errors in this project came from reading a constant next to
the wrong instruction. This analysis deliberately resolved `0x186a0` before using
it — it is `100 000`, an iteration bound, not a voltage. The threshold is the value
*loaded from the struct*, `[x21, #0xbc]`, and its actual number is not in the code.

The same caution applies to `0xbb8` (`3000`), which appears both as a constant in
the function and as `min-dbg-board-id` in the device tree: two occurrences of the
same number is not proof they are the same thing.
