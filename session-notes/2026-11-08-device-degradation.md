# DEVICE DEGRADATION — evidence of a power problem

*Original: `DEVICE_DEGRADATION.md`. Translated faithfully. This file contains the
clearest wrong conclusion of the whole investigation; a correction follows it.*

Date: 2026-11-08, ~01:00

---

## 1. Key observation

**The same file, the same procedure, different results over time.**

### Around 00:15 (session `catch_usbclass`)

```
HELLO ver=3 mode=0
READ[1] ... READ[37] total=1554996
END status=0x0 loops=37 bytes=1554996/1569028
DONE=True
```

**Full transfer, `END 0x0`, `DONE True`.**

### Around 01:00 (session `control_test_v3`)

```
reset -> cmd=0x8
RESULT: empty_rsp  16700/1569028 (1.1%)
```

**The same file. The same script. Stall after 16 700 bytes.**

### Around 01:00 (signed file)

```
reset exc USBTimeoutError   (3 attempts)
preparation failed
```

**Not even the HELLO state can be restored — SAHARA_RESET does not answer.**

## 2. The failure point is always the same

```
[    1.065]   READ[7] off=197376 len=11376 total=16700
[    6.076] timeout loop=7 sent=16700/1569028
```

The same place had appeared earlier in `raw_sahara_fh5.py`:

```
[    1.065]   READ[7] off=197376 len=11376 total=16700
[    6.076] timeout loop=7 sent=16700/1569028
```

So **16 700 B** (after the 7th `READ_DATA`) is an unstable point — sometimes it passes,
sometimes it does not.

## 3. Interpretation

The pattern "it worked, then it stopped, with no code change" points to
**deteriorating physical conditions**, not a software bug:

1. **The battery is discharging.** The tablet has been lying in crashdump for weeks,
   powered mainly from the USB port (~500 mA, not 4.5 A like the charger).
2. **The programmer (melf) has DBC built in** — Dynamic Battery Check:

   ```
   loader-dbc-threshold
   skip-loader-dbc
   vsys-min-recover-mv
   vbatt-min
   battery-low-threshold-mv
   charger is not charging and device will shut down
   ```

3. **The lower the voltage, the shorter the session can be sustained** — which is
   exactly what was observed: 1 554 996 B in the morning → 16 700 B now.

## 4. Why this matters

This is **not** random instability. It is **progressive degradation**, which will stop
all tests regardless of what else we come up with.

Further attempts on a discharged tablet:

- will give false negatives ("the signature does not work" — and that is untrue, it
  simply never reached the verification stage),
- may **deepen the problem** (every interrupted session leaves the device in a dead
  state requiring a reset).

## 5. State of knowledge about the signature — still unresolved

**We do not know whether the signed melf works.** The last test at 00:50 gave `0x21` at
1 109 804 B, but:

```
1 109 804 B  <  1 117 008 B (offset of the firehose image!)
```

**The transfer broke BEFORE it reached the replaced image.** So `0x21`
(hash verification failure) concerned image [2] (XBL core), not our firehose.

That was **an artefact of an interrupted transfer**, not evidence of a bad signature.

**Conclusion: the signature hypothesis is still untested.**

## 6. What needs to be done

1. **Charge the tablet fully** — several hours on a 45 W mains charger, not the USB
   port. Ideally while off or stabilised.
2. After charging, **repeat the control test** (`control_test_v3`):
   - if the original again gives `END 0x0` → conditions have recovered, the signature
     can be tested
   - if it still stalls at 16 700 → the problem is not the battery
3. Only then test the signed melf.

## 7. Test files ready

```
xbl_s_devprg_ns_SIGNED_FH.melf        1 569 036 B   signed firehose v7
xbl_s_devprg_ns_SIGNED_FH_v6.melf     1 569 036 B   signed firehose v6
xbl_s_devprg_ns_PAD_*.melf            1 569 036 B   variants with padding
xbl_s_devprg_ns.melf                  1 569 028 B   original (control)
```

Scripts:

```
control_test_v3_2026-11-08.py   control test orig vs signed (with reset)
test_signed_melf_2026-11-08.py  full signature test
melf_tool.py                    melf structure analysis
build_signed_melf_padded.py     builds variants
```

## 8. Tablet state at the time

```
9008: present
HELLO: pending (cmd=1, ver=3, mode=0) — after a manual SAHARA_RESET
```

The tablet responds, but every transfer attempt breaks early.

---

## CORRECTION (added 2026-11-08, after the morning session)

Two of the three inferences in §3 and §5 were wrong, and the difference matters.

**What was right:** the degradation was real, it was caused by low battery voltage, and
charging made it disappear. A 9-hour charge produced a clean control cycle
(`END 0x0`, 1 554 996 B).

**What was wrong:** the claim that the 16 700-byte stall proved a power problem. The
same stall, at the same offset, was later caused by a **missing zero-length packet**
after a 512-byte-aligned chunk. Two unrelated causes, one identical symptom — and this
file was written while only the first was known.

**What was also wrong:** §5's conclusion that the signature hypothesis was merely
"untested". It was tested later the same morning, on a fully charged tablet, and
returned `0x21` repeatably — so the signature theory did not fail because of the
battery, it failed on its own merits.

The lesson, which is the reason this file is published uncorrected in the body: a shared
symptom between two causes can make a correct observation support an incorrect
diagnosis. The ZLP fix removed the stall; the silence after `DONE` remained. Only
separating those two facts made progress possible.

See [`../docs/03-sahara-protocol.md`](../docs/03-sahara-protocol.md) §9 and
[`../docs/07-dead-ends.md`](../docs/07-dead-ends.md) §E1.
