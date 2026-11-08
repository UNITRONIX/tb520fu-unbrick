# Service report

This is the English version of the report submitted to the repair centre, plus the
payload manifest. The original Polish text is preserved verbatim in
[`../session-notes/2026-11-08-service-report-pl.md`](../session-notes/2026-11-08-service-report-pl.md),
because that is what the service actually received.

The serial number has been replaced with `<DEVICE_SERIAL>` here. It was present in
the submitted document.

---

## 1. Fault description (one page, as submitted)

> Lenovo `TB520FU`, serial `<DEVICE_SERIAL>`.
>
> The tablet was being prepared for deployment in a company project. During a
> change to the system software configuration, including the bootloader layer, the
> operation did not complete successfully. The device does not start Android — on
> power-on it displays the Lenovo logo and then enters Qualcomm diagnostic mode,
> repeating this sequence cyclically. Neither fastboot nor recovery works.
>
> The device is hardware-healthy: no mechanical damage, the housing and screen are
> intact, the battery charges correctly, and communication with a computer in
> Qualcomm emergency mode works correctly. Diagnostics confirmed that the hardware
> layer and the lower boot stages are functional, and that the only damaged element
> is the content of the bootloader partitions.
>
> Please restore the device to factory condition by flashing the original
> manufacturer software, overwriting both bootloader partitions. User data does not
> need to be preserved.

---

## 2. Diagnostic sequence (technical annex)

| # | Test | Result |
|---|---|---|
| 1 | Normal boot, attempt to enter fastboot and recovery | No effect. Lenovo logo, then Qualcomm diagnostic mode. Sequence repeats. |
| 2 | Bootloader menu via Vol+/Vol− at power-on | Keys not read by the bootloader. Menu unreachable. |
| 3 | Forced Qualcomm EDL, including with a dedicated EDL cable | Mode reached. Communication with the device works correctly; the device responds to the protocol. |
| 4 | Flashing the original factory loader from ZUI 18.5.10.037 over Sahara | Transfer complete (1 554 996 B). Device confirms acceptance of the image, but does not start a write session — silence on all commands, then return to diagnostic mode. Repeated many times, identical result. |
| 5 | Four independent tools (custom USB client, `edl`, `QSaharaServer` + `fh_loader`, LTBox) and two operating systems (Windows and native Linux) | Identical result every time. The problem is not on the computer side nor the tool side. |
| 6 | Own loader (signed with test keys, image substituted inside the factory file) | Rejected by the boot processor with an error code. Integrity verification covers the entire signed block; without the manufacturer's key this cannot be bypassed. |
| 7 | Suspicion of insufficient battery voltage | Excluded after 9 hours of charging (full, clean control cycle). |
| 8 | Measurement of device presence on the USB bus at 0.15 ms resolution during the logo window | During this window the tablet does not appear on the USB bus in any mode. |

**Conclusion:** only the content of the bootloader partitions (`abl_a` / `abl_b`)
is damaged. The hardware and the lower boot stages are functional. Writing these
two partitions from service-level EDL access is required. Verified reference images
are available (1 MiB each, with SHA-256 sums) together with the addresses:
`abl_a` LUN 4 / sector 95238, `abl_b` LUN 4 / sector 437686.

---

## 3. Payload manifest

Hand these to the service, or reproduce them from the Lenovo RSA packages
yourself.

| File | Size | SHA-256 |
|---|---|---|
| `stock_abl_a.img` | 1 048 576 B | `4E13E55EC9BFE814404F5E7E71451263F9A3BF7A5B09F495DD40FE6D96822EB7` |
| `stock_abl_b.img` | 1 048 576 B | `2E3D51734AD16F258AA9979BBA0B33AF2164E40040750C1FFF59D8184DB5DEB0` |

### Where the two files came from

| File | Source package | Contents |
|---|---|---|
| `stock_abl_a.img` | `TB520FU_ROW_OPEN_USER_Q00002.0_W_ZUI_17.5.10.096_ST_251127` | ABL, 241 464 B of code + padding to 1 MiB |
| `stock_abl_b.img` | `TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929` | ABL, 270 136 B of code + padding to 1 MiB |

Both are extracted from official Lenovo RSA packages. They are not redistributed
in this repository (see [`11-faq.md`](11-faq.md)); the SHA-256 values are published
so you can confirm you have the right files.

### Target locations

```
partition   LUN   start sector   sectors   size
abl_a        4        95238        256     1 048 576 B
abl_b        4       437686        256     1 048 576 B
```

Sector size on this platform is 4096 bytes, so byte offset =
`start_sector × 4096`:

```
abl_a   byte offset  390 094 848
abl_b   byte offset  1 792 761 856
```

---

## 4. What the service needs to do

Literally:

```
write abl_a  ←  stock_abl_a.img
write abl_b  ←  stock_abl_b.img
reboot
```

Two 1 MiB writes. Total time in a working EDL session: about 30 seconds.

A standard Lenovo service tool with the official RSA package will do this without
any of the above — the offsets and payloads matter only if they are working at
EDL/partition level rather than using their own tooling.

---

## 5. What the service should *not* do

Worth stating explicitly, because a shop that has not seen this device may try:

| Do not | Why |
|---|---|
| Flash a full "rescue" package hoping it overwrites ABL | It will fail at exactly the same step, since the write path is what is broken. |
| Flash `prog_firehose_ddr.elf` as a standalone programmer | Rejected with `0x29` — wrong container for this PBL. |
| Replace the mainboard as a first step | The fault is in flash content, not hardware. Replacing the board is unnecessary cost. |
| Flash an ABL from another Lenovo tablet | Different board; this is how the device was bricked. |
| Assume the eMMC/UFS is failing | Storage responds normally; reads and identification work, only writes are unavailable. |

---

## 6. Outcome of the EDL session for the service

If they get a working write session, verification is straightforward:

1. Read back both partitions.
2. Compare SHA-256 against the manifest above.
3. Reboot. The device should reach Android or at minimum fastboot.

Note that both slots currently hold wrong content, so a `slot-retry-count` reset
may also be needed if the bootloader refuses to try slot `a` after the write. That
lives in `devinfo` (LUN 4, sector 677222) — one sector. Clearing it to a fresh
state is normally done by `fastboot oem` commands on a healthy device; at EDL level
it can be written directly, but only if the service knows the correct contents for
this model. Alternatively, after ABL is restored the bootloader may reset the
counter itself on a successful boot.

---

## 7. Cost reality check

At the time of writing, the alternatives were:

| Option | Cost | Chance |
|---|---|---|
| Authorised service, warranty route | depends on whether the unlock voided it | high — it is two writes |
| Independent shop with EDL (test point) | low, if they have the equipment | high |
| New mainboard | expensive and unnecessary | — |
| Keep trying from the host | free | zero, as documented here |

The honest summary given to the owner was: the technical problem is solved, the
remaining problem is administrative. The correct payloads are known, verified and
in hand; what is missing is permission to write.
