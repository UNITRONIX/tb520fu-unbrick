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

### The loop is bounded, and the timing rules DBC out

`scripts/dbc_trace.py` isolated the third (and last) backward branch in the
recovery function. Its structure:

```
0x14837f48  ldrh w8, [x21, #0xbc]      threshold from the config struct
0x14837f50  ldrh w9, [x29, #-0xc]      measured value
0x14837f58  sub  w22, w8, w9           difference
0x14837f4c  movz w21, #0x86a0
0x14837f54  movk w21, #0x1, lsl #16    w21 = 0x186a0 = 100 000 us = 0.1 s
0x14837f5c  bl   0x148386f8            refresh the reading
0x14837f60  tbnz x22, #31, 0x14837fa8  negative -> EXIT (voltage sufficient)
0x14837f98  mov  w0, w21
0x14837f9c  bl   0x14832ac8            delay(0.1 s)
0x14837fa0  sub  w22, w22, #0x64       reduce the gap by 100 mV
0x14837fa4  b    0x14837f5c            loop
```

**The loop terminates.** It decrements the difference by 100 mV per iteration and
exits when the sign goes negative, so it is bounded by construction:

| gap | iterations | duration |
|---|---|---|
| 400 mV | 4 | 0.4 s |
| 1000 mV | 10 | 1.0 s |
| worst case (u16 max) | 655 | **65.5 s** |

**Measured against the observed failure, this rules the battery gate out.**

The device leaves the bus **8.016 s** after `DONE`. No branch of this loop produces
that figure: the common cases finish in under a second and then proceed, and the
pathological case runs for over a minute. Eight seconds sits in the gap between
them, where this loop cannot place it.

So the DBC hypothesis — which `05-firehose-and-the-silence.md` had dismissed for a
different and insufficient reason — is now dismissed for a measured one.

### What that leaves

The number **8.016 s** is the strongest remaining clue, because it must correspond
to something periodic. The watchdog window measured elsewhere on this platform is
**7.918 s ±3 ms**, leaving roughly **98 ms of work** between the last acknowledgement
and the stall.

That shape — a short burst of activity, then silence — is not a gate that refuses.
It is code that starts something and stops making progress. The remaining work is
therefore to find what the programmer does in those ~98 ms.

---

## 7. No 8-second wait exists anywhere

`scripts/find_8s_loops.py` scanned every `bl` to the known microsecond-delay routines
in all three code images and computed the argument. In the 0.05–30 s range there is
**exactly one** hit:

```
image [2]  0x14837e98   delay 50 000 us = 0.050 s
image [3]  none
image [4]  none
```

So there is no designed sleep anywhere near 8 s. That settles the shape of the
failure: **8.016 s is not a wait, it is a window.** The programmer ran, did something
briefly, and stopped advancing — and the watchdog then collected it after its
7.918 s of patience expired.

The ~98 ms difference between 8.016 s and 7.918 s is the only evidence about how much
work actually happened before the stall. That is a very short burst, which is
consistent with a failure early in a call rather than a long computation.

---

## 8. The watchdog surface

`scripts/watchdog_map.py` enumerates every watchdog-related string and the code that
references it:

```
0x148ad6dd  "Pet Charger wdog failed"         ref 0x14837bd8
0x148ac116  "boot_wdog_disable_check"         no direct refs (symbol table)
0x148ac6e9  "xbl_sc_wdog"                     no direct refs
0x148ab132  "RST:APPS_WDOG_BITE"              ref 0x14827848
0x148ab145  "RST:AOP_WDOG_BITE"               ref 0x14827854
0x148ad992  "WDog S2"                         ref 0x14838f34
0x148ab91e  "WatchDogTimerLib.c"              ref 0x1482c3cc
```

Two things worth noting:

- **`"Pet Charger wdog failed"`** — the firmware separately services a *charger*
  watchdog. That is a different beast from the SoC watchdog and it is a reminder that
  "the watchdog fired" is not automatically about the CPU.
- **`"WDog S2"`** appears in a reset-reason name table alongside `Resin S2`,
  `PSHOLD`, `SW Reset`, `RTC`. So `RST_STAT = 0x3` reading as "watchdog" is consistent
  with a named, enumerable reset cause rather than an inference.

There is also a `boot_wdog_disable_check` symbol, i.e. code that can *check* whether
disabling the watchdog is permitted. It is compiled in. Its reference site was not
found by string search because it is a symbol name, not a used literal — following it
would require symbol resolution rather than string cross-reference, which is a
different technique and beyond what this pass established.

---

## 9. Method note

Two earlier arithmetic errors in this project came from reading a constant next to
the wrong instruction. This analysis deliberately resolved `0x186a0` before using
it — it is `100 000`, an iteration bound, not a voltage. The threshold is the value
*loaded from the struct*, `[x21, #0xbc]`, and its actual number is not in the code.

The same caution applies to `0xbb8` (`3000`), which appears both as a constant in
the function and as `min-dbg-board-id` in the device tree: two occurrences of the
same number is not proof they are the same thing.
