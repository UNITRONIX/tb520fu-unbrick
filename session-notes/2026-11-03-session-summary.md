# TB520FU Fedora port — session summary

*Session of 2026-11-03. Originally written in English; reproduced with paths
generalised and the device serial redacted.*

Device: **Lenovo Yoga Tab Plus / TB520FU** (codename *lapis*)
SoC: **Qualcomm SM8650 (Snapdragon 8 Gen 3 / "pineapple")** — not MediaTek Helio G99
OS when last confirmed healthy: **Android 16** (ZUI 17.5.10.096 build lineage),
**bootloader unlocked** (`unlocked: yes`, verified boot **orange**)

---

## 1. What was achieved

### Kernel / DT path

- Stock-derived custom DT in `vendor_boot` was already known to boot Android.
- **Stock kernel + pivot initramfs RAM-tested earlier that evening** and confirmed
  working (before the persistent `init_boot` experiments).

### Fedora userspace

- Minimal **Fedora rootfs** built and placed on the tablet at
  **`/data/tb520fu_fedora` (~272 MB)**.
- Tree still present after the Magisk work (verified with root).

### Boot images

- **`init_boot_pivot.img`** created (GKI: the ramdisk lives in `init_boot`, not `boot`).
- Early pivot (~648 KB) flashed and exercised; later rebuilt with USB/OTG targeting
  and Android fallback logic.
- The **`boot` partition was not modified** during these tests (by design).

### Magisk

- Bootloader already unlocked.
- Magisk-patched image from `/data/local/tmp/magisk_patch/new-boot.img` flashed to
  **`init_boot` only**.
- Result: **Magisk 30.7** present — `su` → `uid=0` (`u:r:magisk:s0`), package
  `com.topjohnwu.magisk`, Android booted normally.
- Note: Magisk does **not** remove FBE for a cold-boot pivot; `/data` remains
  file-based encrypted (`inlinecrypt` f2fs).

### Ventoy USB (PC side — read-only inspection plus one new file)

- Stick: **USB SanDisk 3.2Gen1**, ~**460 GB**
- Layout: **MBR** — large **exFAT `Ventoy`** data partition plus a small
  **FAT `VTOYEFI`** (~32 MB)
- Free space on the data volume (after copying): ~**373 GB**
- Because **exFAT cannot host a Linux rootfs** (symlinks and permissions), the Fedora
  tree was packed into:
  - **`<USB_DRIVE>:\tb520fu_fedora.ext4`** — a **512 MiB** ext4 image containing the
    ~282 MB rootfs (from the device tar)
- The EFI partition and existing ISOs were left alone, apart from adding that single
  `.ext4` file on the data volume.

### Pivot rebuild aimed at OTG

- Pivot updated to look for **`tb520fu_fedora.ext4`** on USB (exFAT mount +
  `losetup`), with the stock first-stage ELF embedded as **`/init.android`**.
- Rebuilt image size after embedding stock init: **`init_boot_pivot.img` ≈ 2.37 MiB
  (`2 482 176` bytes)** — fits the real **`init_boot` = 8 MiB (`0x800000`)**, not
  96 MiB.

Key paths:

| Artifact | Path |
|---|---|
| Pivot image | `<ROM_DIR>\mainline\bootimg\init_boot_pivot.img` |
| Pivot sources | `<ROM_DIR>\mainline\bootimg\fedora_minimal\` (`pivot_init.sh`, `mk_initramfs_wsl.sh`, …) |
| Fedora ext4 on Ventoy | `<USB_DRIVE>:\tb520fu_fedora.ext4` (when the stick is mounted on the PC) |
| Stock `init_boot` backup | `<ROM_DIR>\stock_images_ZUI_17.5.10.096\init_boot.img` |
| Magisk pull copy | `<ROM_DIR>\mainline\bootimg\magisk_new-boot.img` |

---

## 2. What failed

### Persistent pivot without USB

Flashing the non-Magisk **`init_boot_pivot`** and rebooting **without** OTG →
**hang on the Lenovo logo**, no ADB, no recovery UI over USB.

The emergency `/bin/sh` fallback has **no USB gadget**, so the device looks "dead"
to the PC.

### The "12-second fallback to Android" did not work

- First fallback design: after a USB timeout, `exec /init.android` (stock first stage).
- The device still hung on the logo; it later returned to **fastboot** after failed
  boot attempts (`slot-retry-count:a` observed at 6).
- Likely contributing bug: the early pivot scanned **`/dev/sda*` / `sdb*`**, but on
  this platform **internal UFS already appears as `sd[a–f]`**. Mounting internal
  volumes as "OTG" can **block before the Android fallback** ever runs.

### The "fixed" pivot (removable-only scan + `/init` handoff) also failed

- Fix applied in the tree: probe only **`removable=1`** block devices; on a miss, copy
  the stock ELF over `/init` and `exec /init`.
- Image rebuilt (**~2.4 MB**) and **successfully flashed** to `init_boot` at
  **~22:52** (`FLASH_OK`, write OKAY).
- After reboot: **still Lenovo logo for 60–90+ s**, **no ADB**, **no fastboot** until
  the user force-booted the bootloader.
- Conclusion: **the Android fallback is still broken** even after the UFS-as-USB fix;
  do not rely on this pivot for safe dual-boot yet.

### FBE / Fedora-from-`/data`

A cold pivot cannot usefully mount **`/data/tb520fu_fedora`** under FBE.

The viable direction remains **unencrypted root on USB OTG**
(`tb520fu_fedora.ext4`), not Magisk-on-`/data`.

---

## 3. Current state (end of session)

| Item | State |
|---|---|
| **`init_boot`** | Holds the **broken ~2.4 MB "fixed" pivot** (last successful flash ~22:52). **Not** Magisk, **not** stock. |
| **Android** | **Not booting** with the current `init_boot`. Last known good Android 16 was **before** the later pivot flashes (the Magisk era was healthy). |
| **USB visibility** | Often **offline** while stuck on the logo; restoring it needs **Vol− + Power → fastboot**. |
| **`boot`** | Untouched (per the session constraints). |
| **`/data/tb520fu_fedora`** | Should still be intact (~272 MB); not verified after the last hang. |
| **Ventoy** | Still has **`tb520fu_fedora.ext4`** (~512 MB) on the exFAT data partition. |
| **Bootloader** | Unlocked; product `lapis`; serial `<DEVICE_SERIAL>`; slot **a**. |

**Stock restore image (ready on the PC, not yet confirmed restored at the time of
writing):**
`<ROM_DIR>\stock_images_ZUI_17.5.10.096\init_boot.img`

---

## 4. Next steps

1. **Restore stock `init_boot` immediately** (device in fastboot):

   ```bat
   fastboot flash init_boot "<ROM_DIR>\stock_images_ZUI_17.5.10.096\init_boot.img"
   fastboot reboot
   ```

   Confirm Android 16 + ADB before any further pivot work.

2. **Optional:** re-flash the Magisk `init_boot` only if root is needed again for
   file management (it does not solve cold-boot FBE).

3. **Retry Fedora via OTG only after Android is stable:**
   - Plug the Ventoy stick (with `tb520fu_fedora.ext4`) into the tablet OTG.
   - Use a pivot that is proven **not** to brick the no-USB path — until the fallback
     is fixed and tested, prefer **RAM-boot / non-persistent** experiments, or keep
     stock `init_boot` and only test with a carefully gated image.
   - Do **not** leave a broken pivot on `init_boot` overnight.

4. **Pivot engineering still needed:**
   - Prove the Android fallback with serial/`earlycon` or a known-good chainload
     (stock first stage as the real PID 1, or a Magisk-style ELF wrapper).
   - Never treat internal `sd*` as USB; only removable / by-path USB.
   - Keep `boot` and the Ventoy EFI untouched unless explicitly required.

---

## 5. Session constraint reminder

- Prefer **RAM-boot** and selective flashes; restore stock on failure.
- **Do not** flash `boot` or wipe `data` / Ventoy for these experiments.
- The real `init_boot` size is **8 MiB**, not 96 MiB.

---

*Written 2026-11-03 for handoff; no flash performed while creating this file.*

---

> **Retrospective note (added when publishing):** step 1 above — restore stock
> `init_boot` immediately — was the correct and sufficient fix. It was not applied
> before the next phase, which replaced both ABL slots instead. See
> [`../docs/01-timeline.md`](../docs/01-timeline.md).
