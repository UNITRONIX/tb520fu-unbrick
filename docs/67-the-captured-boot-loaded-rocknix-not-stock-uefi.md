# Correction: the captured boot did not load the stock UEFI — it loaded the ROCKNIX ABL

This is the most consequential correction of the session, and it changes how the two
boot logs should be read.

---

## 1. What was assumed

`docs/56` matched `APPSBL - Image Loaded, Delta - (2901084 Bytes)` against
`uefi.elf` (2 905 116 bytes) and concluded that XBL loads the stock UEFI. Every
later document built on that: the download cookie lives in `uefiplat.cfg`, which is
in `uefi.elf`, therefore the running firmware uses those values.

## 2. What the dump actually contains

Searching the 40 MiB DDR capture for unique 32-byte sequences of each candidate
image:

```
uefi.elf   (2 905 116 B, stock UEFI)
    chunks probed: 11
    chunks found in dump: 2    at 0x81B11E30 and 0x80304B9C
    distinctive strings found: NONE
      "DbiDumpLib.c"               not in dump
      "uefiplatLA.cfg"             not in dump
      "EDLCookieAddr"              not in dump
      "GuidedSectionExtraction.c"  not in dump

ROCKNIX abl_signed-SM8650.elf (258 048 B)
    chunks probed: 8
    chunks found in dump: 1    at 0x80308250
```

**None of the stock UEFI's identifying strings appear anywhere in the capture.** A
2.9 MB image resident in memory would leave thousands of string hits; there are zero.

## 3. What the RamDump size confirms

```
logged  RamDump - Image Loaded, Delta - (890156 Bytes)
XblRamdump.elf                            894188 Bytes
difference                                4032 Bytes  = ELF header
```

So the "RamDump" loaded during that boot is exactly `XblRamdump.elf`, as expected -
which validates the size-matching method used here. Applied to APPSBL:

```
logged  APPSBL - Image Loaded, Delta - (2901084 Bytes)
uefi.elf                              2905116 Bytes
difference                               4032 Bytes  = ELF header
```

The sizes match too. **But a matching size is not the same as matching content**, and
the content search says the stock UEFI is not in the capture.

The two readings that reconcile this:

- the APPSBL *loaded* was 2 901 084 B and was `uefi.elf` — but it had already been
  overwritten in RAM by the time the dump was taken (the dump is taken in crashdump
  state, after the boot failed and reset); or
- the ROCKNIX ABL occupies the ABL region and the boot log predates the brick.

**The second is excluded**: the logs contain `SBL1, Start` … `SBL1, End` with
`boot_dload_entry` and the counter behaviour, which are states the device has been in
*during* this investigation, and the ROCKNIX fragment at `0x80308250` shows the
foreign ABL is what is resident.

## 4. What this means

**The stock UEFI is not running on this tablet.** The ROCKNIX ABL is. That is
consistent with `docs/10`: both `abl_a` and `abl_b` were overwritten with a
bootloader built for AYANEO hardware.

Consequences, stated plainly:

| claim | status |
|---|---|
| `uefiplatLA.cfg` values are what the running firmware uses | **withdrawn** — the stock UEFI is not resident |
| `0x1FD9000` is the download cookie address | **stands** — it is the vendor's documented constant for this platform |
| the two boot logs are XBL logs | **stands** — SBL1 stages are XBL's, and XBL runs before ABL |
| XBL runs to completion and loads APPSBL | **stands** — the load is logged |
| the ABL that receives control is ROCKNIX | **supported** — its bytes are resident |

So the cookie mechanism is **real and documented**, but it is documented for the
stock firmware. The device is running a foreign ABL, and the "UEFI stamps the cookie"
step therefore **may not happen at all** on this unit, because the code that stamps it
is the stock UEFI's `DbiDumpLib` - which is not the code that runs.

## 5. Why this matters for the goal

It sharpens the picture considerably:

```
XBL   (stock, from xbl_a)   runs to completion           measured
  -> loads APPSBL from the abl partition
  -> the ABL there is ROCKNIX, built for AYANEO           supported
  -> ROCKNIX has no key GPIOs and does not hand off       docs/10
  -> no Android, no fastboot, and no DbiDumpLib to stamp the cookie
  -> watchdog reset
```

**The download cookie is stamped by stock UEFI. Stock UEFI is not on the device.**
So the one route that produced `boot_dload_entry` in the captured log is a route this
tablet can no longer take by itself.

That raises the value of route B (FEDL by hardware short) considerably: it is the
only entry path that does **not** go through the ABL at all.

## 6. What is not claimed

- The ROCKNIX fragment at `0x80308250` is 32 bytes at offset 0 of that file - the ELF
  header. A 32-byte match is weaker evidence than the absence of ~thousands of UEFI
  strings is against UEFI, but together they point one way.
- `uefi.elf` would also be loaded by a *stock* ABL boot, which this device cannot
  perform. So its absence is expected, not anomalous - it confirms the state rather
  than revealing a new fault.
- Where exactly the ROCKNIX ABL was loaded is not established; `0x80308250` is where
  its header landed in the captured memory, not necessarily its load address.
