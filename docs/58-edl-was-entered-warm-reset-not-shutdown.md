# EDL was entered once — and the difference is TCSR, the RamDump image, and `boot_dload_entry`

`docs/57` compared two boot logs. This document reports what the difference actually
is, and it is the answer to why the device emitted a HELLO earlier today and not
since.

---

    10|## 1. The older boot entered EDL. The newer one did not.

```
=== A  (0x81A00000, Warm Reset) ===
B - 847168 - TCSR reg value 0x10
D -      0 - ramdump_load_cancel
B - 847168 - RamDump -  Image Load, Start
D -   3050 - Auth Metadata
D -  15402 - RamDump -  Image Loaded, Delta - (890156 Bytes)
B - 862601 - boot_dload_entry          <-- EDL ENTERED
B - 863607 - SBL1, End

=== B  (0x81CE4000, Shutdown) ===
D -      0 - ramdump_load_cancel
B - 811178 - RamDump -  Image Load, Start
D -      0 - RamDump -  Image Loaded, Delta - (0 Bytes)     <-- nothing loaded
D -     61 - boot_update_abnormal_reset_status
...                                                          <-- no boot_dload_entry
```

Three differences, in the order they appear:

1. **`TCSR reg value 0x10` appears only in the older log.** The newer log has no
   such line at all.
2. **`RamDump` loads 890 156 bytes in the older boot and 0 bytes in the newer.**
3. **Only the older boot reaches `boot_dload_entry`**, which is the function that
   hands control to the download path.

## 2. Why `0x10` matters

`docs/40` decoded the forced-download timeout stage:

```
0x14863268  bl 0x1484396c          TCSR 0x1FD9000, bits 0x30
0x1486326c  ldrh w8, [x29, #0x1c]  property 0x0c (the timeout)
0x14863270  tst w0, #0xff
0x14863274  b.ne 0x148632c0        bits set   -> skip arm
0x14863278  cmp w8, #0x10
0x1486327c  b.eq 0x148632c0        timeout == 0x10 -> skip arm
```

The log line `TCSR reg value 0x10` is that comparison being evaluated and printed.
In the older boot it was **`0x10`**, which takes the *skip* arm of the forced-download
timeout stage. In the newer boot the line is absent, meaning that stage took a
different branch before reaching the print.

That difference is upstream of everything else, and it is the first boot-to-boot
variation found that touches the download path directly.

## 3. Why the RamDump image matters

`RamDump` is the crash-dump handler image (`XblRamdump.elf`, `docs/50`). The older
boot loaded **890 156 bytes** of it; the newer boot loaded **nothing**.

So on the boot that reached EDL, the download/ramdump code was present in memory.
On the boot that did not, it was not loaded at all. That is not a subtle state
difference - it is the difference between having the code and not having it.

## 4. What this changes about the whole investigation

`docs/35` concluded "the 900E node emits no HELLO" and treated it as a device state
that could not be moved. The logs say something more specific and more useful:

**the device has two distinct boot outcomes**, and they are distinguishable *before*
USB is involved:

| | older boot | newer boot |
|---|---|---|
| reset type | Warm Reset | Shutdown |
| `TCSR reg value` | `0x10` printed | not printed |
| RamDump image | 890 156 B loaded | 0 B |
| `boot_dload_entry` | **reached** | not reached |
| outcome | EDL, HELLO available | crashdump only, silent |

That means the goal - `HELLO ver=3 mode=0` - is **reachable on this hardware**, and
was reached, and the question is what makes the boot take the first path instead of
the second.

## 5. The candidates, from the logs alone

- **`Reset Type`.** The working boot followed a *Warm Reset* (three stacked
  `Reset by PSHOLD` / `Warm reset count 0x3,0x2,0x1`). The failing one followed a
  *Shutdown*. A warm reset preserves state that a shutdown clears - and the older
  log shows DDR recovery (`PASS1 Cookie 0xcafe1111`, `HAL_DDR_SDI_Recover`) that the
  newer one did not need.
- **The TCSR stamp.** `docs/40` showed the forced-download path *writes* the low six
  bits of `0x1FD9000` with the route it selected. A warm reset keeps that register;
  a shutdown may not. If the working boot inherited a TCSR value from the failed one
  before it, that is the mechanism.
- **The RamDump image load** follows the TCSR decision, so it is probably an effect
  rather than a cause.

**This is a hypothesis, labelled as such.** But it is now a hypothesis with two
logged observations on either side of it, rather than a guess.

## 6. The concrete next test

The pattern predicts: **a warm reset, not a shutdown, is what reaches EDL.**

```
1. from the current state (900E, silent), issue a warm reset rather than a power-off
   - i.e. do not hold Power until the screen dies; do not remove power
2. watch for the device to come back
3. read the XBL log again from RAM and check for three lines:
     "TCSR reg value 0x10"
     "RamDump -  Image Loaded ... (890156 Bytes)"
     "boot_dload_entry"
```

If all three appear, the device has entered the download path, and `9008` with a
fresh HELLO is the expected result. `scripts/tablet.py status` will show it.

That is a test of a stated mechanism, not another blind attempt - and if it fails,
the log will say which of the three lines is missing, which is itself the next
datum.
