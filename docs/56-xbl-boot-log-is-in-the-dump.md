# The XBL boot log is in the dump — and it changes several conclusions

`docs/54` and `docs/55` spent effort on a three-halfword table at `0x800DF408`,
interpreting one value as a possible HWID and concluding the table was constant.
All of that was unnecessary: the **log those values come from is in the same dump**,
in plain text, with its own labels.

It was found by searching the RAM capture for the strings `blacklist` and
`trial_boot`, which led to `0x81CE0000` - the XBL log ring.

---

    10|## 1. The header, verbatim

```
Format: Log Type - Time(microsec) - Message - Optional Info
Log Type: B - Since Boot(Power On Reset),  D - Delta,  S - Statistic
S - QC_IMAGE_VERSION_STRING=BOOT.MXF.2.1-01898.1-LANAI-1.77033.2
S - IMAGE_VARIANT_STRING=SocLanaiLAA
S - Boot Interface: UFS
S - Secure Boot: On
S - Boot Config @ 0x221c8600 = 0x00000001
S - JTAG ID @ 0x221c8744 = 0x202280e1
S - OEM ID @ 0x221c8700 = 0x00000040
S - Serial Number @ 0x221c8610 = 0x00000448147d8aa5
S - Feature Config Row 0 @ 0x221c2130 = 0x003fffffffffbf00
S - Feature Config Row 1 @ 0x221c2138 = 0x00ffff01fe1fff00
S - Core 0 Frequency, 1363 MHz
S - PBL Patch Ver: 7
S - PBL freq: 600 MHZ
```

## 2. This corrects `docs/54` outright

`docs/54` read `0x202280E1` at `0x800DF408` and could not decide whether it contained
the HWID `0x2280E1`. The log answers it, with labels, for all three values:

| address | value | what the log calls it |
|---|---|---|
| `0x221C8600` | `0x00000001` | **Boot Config** |
| `0x221C8744` | `0x202280E1` | **JTAG ID** |
| `0x221C8700` | `0x00000040` | **OEM ID** |
| `0x221C8610` | `0x00000448147D8AA5` | **Serial Number** |

So:

- `0x202280e1` is the **JTAG ID**, not the HWID. The resemblance to `0x2280e1` is a
  coincidence of the low halfword, and `docs/54` was right to refuse the claim.
- `0x0040` is the **OEM ID**.
- `0x8AA5` is the **low half of the serial number** `0x00000448147d8aa5` - the same
  serial `B6F2DE0A` is the other one logged later (`usb: UFS Serial - b6f2de0a`).
- All three being constant across boots (`docs/55`) is now fully explained:
  they are hardware identifiers. The whole "snapshot table" reading was wrong -
  `CD_STRCT` copies identification registers into a table, it does not snapshot
  crash state.

## 3. What the boot log says about the entry paths

```
D -       366 - boot_fedl_check
D -         0 - boot_dload_handle_forced_dload_timeout
D -       366 - sbl1_load_ddr_training_data
```

Both entry stages **ran and returned in 366 µs combined**. They did not hang, and
they did not enter EDL. So on this boot:

- `boot_fedl_check` found no D+ condition (as expected - no short was applied);
- `boot_dload_handle_forced_dload_timeout` did nothing (0 µs).

That is the behaviour the code predicts for an unforced boot, and it confirms the
two functions are reachable and cheap - not blocking.

## 4. The power findings

```
B - 332877 - PM: Reset by PWR & Resin S2
B - 332877 - PM: Reset Type: Shutdown
B - 332877 - PM: PON by PWR key DEB
B - 332877 - PM: PON by SYSOK
```

and

```
B - 462380 - UFS Gear 1 due to low battery
B - 710619 - PM: VBAT: 3588mV IBAT: 0mA
B - 503890 - usb: chgr - CDP_CHARGER
B - 704733 - usb: usb_dp_toggled_for_cdp , 0xc8
```

Two facts worth carrying forward:

- **`Reset Type: Shutdown`** - the PMIC records this boot as following a *shutdown*,
  not a watchdog reset. That is a different value from `RST_STAT = 0x3` seen
  earlier (`docs/15` §5), which means the device has been through both kinds of
  cycle and the log distinguishes them.
- **`VBAT: 3588mV`, `UFS Gear 1 due to low battery`** - the battery is genuinely low
  enough that UFS dropped to Gear 1. This is a real, measured condition. It is not
  what blocks the programmer (that was ruled out in `docs/19`), but it **does**
  mean every subsequent attempt is running on a weak supply, and `docs/07` §E1
  already recorded that low battery degrades transfers in confusing ways.

## 5. Storage and configuration

```
B - 425200 - UFS INQUIRY ID: MICRON  MT512GAYAX4U40  0103
B - 428067 - UFS Boot LUN: 1
B - 431971 - UFS Total Size: 512 GB
B - 491355 - CDT not found in any storage media, using defaults
B - 491385 - CDT -  Image Load, Start
B - 491385 - CDT not found in any storage media
```

`CDT not found in any storage media, using defaults` is exactly the fallback path
`docs/16` §4.2 asked about and could not check. It **is** hit on this unit. That
matters because `docs/16` identified the fallback as "where a board-specific
mismatch would appear".

## 6. The log ends with a complete SBL1

```
B - 1076528 - APPSBL -  Image Load, Start
D -     31842 - APPSBL -  Image Loaded, Delta - (2901084 Bytes)
D -         0 - sbl1_save_appsbl_index
B - 1109346 - SBL1, End
```

**SBL1 runs to completion and loads APPSBL** - 2 901 084 bytes of it - then ends.
So XBL finishes. Whatever fails, fails **after** this point, i.e. inside ABL or in
the handoff to it. That is consistent with `docs/10`'s account (a foreign ABL that
does not hand off) and it rules out any theory in which XBL itself dies.

Taken with `docs/16` §1: the EDL path does not execute ABL, which is why the
programmer's failure and the ABL's failure are two separate problems. This log
confirms the first half of that from the device's own record.

## 7. Where this leaves things

- The "snapshot table" thread is **closed and explained** (identification registers,
  not crash state).
- The FEDL and forced-download stages are **confirmed working and cheap**, not
  blocking.
- The battery is **measurably low** (3588 mV, UFS Gear 1) - a real condition that
  should be fixed before further attempts.
- XBL **completes**; the failure is downstream, in the ABL / handoff.
- The dump we already hold contains **more than was ever read from it**, and the
  fastest way to understand this tablet is to read the rest of this log rather than
  to disassemble more code.
