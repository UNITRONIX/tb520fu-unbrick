# Hardware, drivers and rooting

Everything the kit told us about the device itself: what silicon is inside, which
kernel modules drive it, which firmware blobs it needs, and how the root was done.

This is an inventory with provenance, not a spec sheet. Every part number below
came out of a file on the device or in the Lenovo package, and the file is named so
you can re-derive it.

---

## 1. The device, definitively

| Field | Value | Where it came from |
|---|---|---|
| Model | `TB520FU` | `ro.product.model`, `getvar product` → `lapis` |
| Region variant | `TB520FU_EEA` | build fingerprint in `persist/fingerprint.txt` |
| Codename | `lapis` | `getvar product`, DTB filename, `hmtnv20_Lapis.bin` |
| SoC | Qualcomm **SM8650**, Snapdragon 8 Gen 3 | `qcom,sm8650-*` compatibles throughout the DTB |
| Platform codename | **`pineapple`** (Qualcomm) / **`LANAI`** (firmware build names) | see §2 |
| GPU | Adreno 750 (`gen70900` firmware family) | `vendor_firmware/gen70900_*.fw` |
| Storage | UFS 4.0, 6 LUNs | `gpt_*.bin` 0–5, `rawprogram0..5.x` |
| Display | 12.7" dual-DSI, 3K, DSC, 120 Hz-class | `lapis_tianma_nt36532_dsc_3k_video` in `msm_drm.ko` |
| Touch | Novatek **NT36532** | panel calibration filename, driver strings |
| Stylus | Novatek active pen (integrated, not Wacom) | `nvt_36xxx.ko` pen paths |
| Keyboard | Pogo-pin folio over UART | `lenovo_keyboard.ko` (uart + gpio symbols) |
| Fingerprint | Goodix, in TEE | `goodixfp64.mbn`, `goodix_fp.ko` |
| Wi-Fi/BT | WCN7850-family (`kiwi_v2` / QCA6750 class) | `qca_cld3_kiwi_v2.ko`, `icnss2.ko` strings |
| Last shipping OS | Android 16, ZUI 17.5.10.096 (EEA) / 18.5.10.037 (ROW) | fingerprints, package names |

### Build fingerprint (proof of the exact build)

```
Lenovo/TB520FU_EEA/TB520FU:16/BQ2A.250610.001-BP2A.250605.031.A3/ZUI_17.5.10.096_251127_ROW:user/release-keys
```

---

## 2. A naming trap worth documenting: `pineapple` vs `LANAI`

This cost time, so it is written down.

The SoC is SM8650, whose Qualcomm platform codename is **`pineapple`**. That is what
appears in kernel module names and in upstream Linux:

```
debugcc-pineapple.ko
mixer_paths_pineapple_cdp.xml
audio.primary.pineapple.so
```

But every firmware component in `ver_info.txt` is built as **`LANAI`**:

```
"adsp"        : "LPAIDSP.HT.1.0-00757-LANAI-1"
"boot"        : "BOOT.MXF.2.1-01767.1-LANAI-1"
"tz"          : "TZ.XF.5.28-00043-LANAIAAAAANAZT-1"
"Meta_Build_ID": "Lanai.LA.1.0.r1-00815-STD.PROD-1"
```

`LANAI` count in `ver_info.txt`: **22**. `pineapple` count: **0**.

**Both are correct.** `pineapple` is the silicon platform; `LANAI` is Qualcomm's
internal build/target name for this board family. Practical consequence:

- Searching for `pineapple` finds drivers and audio configs.
- Searching for `lanai` finds firmware, sensor registries and DSP images.
- Neither term alone finds everything. Search both.

This also explains a file that looks contradictory: `lanai_bu52053nvx_0_lapis.json`
— `lanai` (platform), `lapis` (device), `bu52053nvx` (hall sensor chip). Three
naming layers in one filename.

---

## 3. Kernel modules

Two DLKM partitions, 340 modules total, all built for **GKI 6.1.112**:

```
system_dlkm/6.1.112-android14-11-g75d944e80501-ab13981564/   60 .ko
vendor_dlkm/                                                280 .ko
```

The kernel version string matters: these `.ko` files load **only** into that exact
GKI build. They are useless on a mainline kernel and must be rebuilt for anything
else. Anyone planning a Linux port should not expect to reuse them.

### Board-specific modules (the interesting ones)

| Module | Size | Drives |
|---|---|---|
| `lenovo_keyboard.ko` | 99 544 | folio keyboard |
| `hall_mod.ko` | 25 808 | hall sensor, folio attach / lid |
| `nvt_36xxx.ko` | 478 168 | Novatek touch **and** stylus |
| `nt36xxx-i2c.ko` | 231 920 | Novatek, I²C transport variant |
| `goodix_ts.ko` | 346 864 | Goodix touch (secondary or other SKU) |
| `goodix_fp.ko` | 83 168 | Goodix fingerprint bridge |
| `msm_drm.ko` | 5 021 744 | display, and the panel registration strings |
| `panel_event_notifier.ko` | 15 976 | panel state events |
| `qca_cld3_kiwi_v2.ko` | 19 180 136 | Wi-Fi, `kiwi_v2` SKU |
| `cnss2.ko`, `icnss2.ko`, `cnss_utils.ko` | — | WLAN subsystem plumbing |
| `qti_battery_charger.ko` | 132 040 | charging, PMIC |
| `pmic_glink.ko`, `charger-ulog-glink.ko` | — | Type-C / PD over GLINK |
| `wcd_usbss_i2c.ko` | 91 968 | USB Type-C switch |
| `dwc3-msm.ko` | — | USB device/host controller |
| `phy-msm-snps-eusb2.ko`, `phy-msm-ssusb-qmp.ko` | — | USB2 / USB3 PHYs |
| `phy-qcom-ufs-qmp-v4.ko` | 27 312 | UFS PHY |
| `i2c-msm-geni.ko`, `spi-msm-geni.ko` | — | I²C / SPI controllers |

### What the panel strings reveal

`msm_drm.ko` contains the panel names the bootloader and display driver know about:

```
lapis_tianma_nt36532_dsc_3k_video
lapis_boe_nt36532_dsc_3k_video
```

**Two panel vendors**, both NT36532 touch, both 3K with DSC, both "video mode" DSI.
A Linux port must ship firmware for both and pick the right DTB — which is exactly
why the kit carries four Novatek firmware files (§5).

---

## 4. Rooting, exactly as it was done

Recorded from the Magisk flash log, so this is the procedure that actually worked on
this device — not a generic guide.

### The critical detail: `init_boot`, not `boot`

This is a **GKI** device with `header_version 4` boot images. The ramdisk lives in
`init_boot`, not in `boot`. Patching `boot` with Magisk on this class of device
either does nothing or breaks the boot.

Measured image facts:

| Image | Size | `kernel_size` | `ramdisk_size` |
|---|---|---|---|
| `boot.img` | 100 663 296 | 35 289 600 | **0** |
| `init_boot.img` | 8 388 608 | **0** | 2 099 409 |
| `recovery.img` | 104 857 600 | 0 | 16 164 386 |

`boot` has a kernel and no ramdisk. `init_boot` has a ramdisk and no kernel. That is
the whole argument.

### Procedure

1. Unlock the bootloader — see [`12-bootloader-unlock.md`](12-bootloader-unlock.md).
   Expected state afterwards: `ro.boot.flash.locked=0`, `verifiedbootstate=orange`.
2. Extract `boot.img` / `init_boot.img` / `recovery.img` from the RSA package for
   your exact build.
3. Patch **`init_boot.img`** with Magisk (v30.7 was used) — in the app, or via
   `boot_patch.sh` with `KEEPVERITY=true` and `KEEPFORCEENCRYPT=true`.
4. Flash and reboot:

   ```bash
   fastboot flash init_boot magisk_patched_init_boot.img
   fastboot reboot
   ```

5. Verify:

   ```bash
   adb shell /debug_ramdisk/magisk su -c id
   # uid=0(root) gid=0(root) context=u:r:magisk:s0
   ```

Result on this unit: Magisk `30700`, package `com.topjohnwu.magisk`, `su` working,
Android booting normally.

### Stock checksums, so you can confirm your extraction

```
efa6be0b5cfd17218846cc173cebfd463de129051ded4daca2c98361275f9e2f  boot.img
b07e2e5262a356a6feb3f21cddca098d7c3d7912dbd39b183f3f8f60e41a5031  init_boot.img
9494d534e6bd3b1190022688804eddc93840f14979eb057c4c10833b131a922b  recovery.img
```

(from ZUI 17.5.10.096, `stock_images_ZUI_17.5.10.096/SHA256SUMS.txt`)

### What Magisk does not do here

Magisk does **not** remove file-based encryption for a cold-boot pivot. `/data`
stays FBE-encrypted (`inlinecrypt` on f2fs), so a custom initramfs cannot mount it
before Android has unlocked the keys. This is what killed the "Fedora on `/data`"
idea — see [`08-linux-port-notes.md`](08-linux-port-notes.md) §6.

---

## 5. Firmware inventory

All of it extracted from the stock device with root, sizes as measured.

### GPU — Adreno 750

```
gen70900_sqe.fw        85 364
gen70900_aqe.fw        33 176
gmu_gen70900.bin       78 588
gen70900_zap.mbn       12 088
```

Also present: `gen71100_*.fw` (a different Adreno generation, shipped in the same
firmware partition for other SKUs — not used by this board).

For Linux these go under `/lib/firmware/qcom/` and the kernel side is `drm/msm` +
GMU. The proprietary userspace blobs below are **Android-only** and cannot be used
on glibc:

```
libGLESv2_adreno.so   4 828 288     libgsl.so            2 276 432
libCB.so              2 893 216     vulkan.adreno.so     3 291 272
libadreno_utils.so       93 776     libOpenCL_adreno.so    167 880
```

### Touch and stylus — Novatek NT36532

Four firmware files, because there are two panels and two calibration variants:

```
novatek_ts_tianma_fw.bin     245 760
novatek_ts_tianma_mp.bin     245 760
novatek_ts_boe_fw.bin        245 760
novatek_ts_boe_mp.bin        245 760
```

Plus the factory calibration for the Tianma panel, which is per-unit data and
should not be overwritten:

```
display/factory_calib_data_nt36532_tianma_3k_video_mode_dsi_panel.json   350 426 B
```

The `nvt_36xxx.ko` driver carries the pen support — its strings include
`nvt_pen_diff`, `nvt_pen_max_pressure`, `pen_2d_raw_tip_x/y`. So the stylus is
handled by the same digitizer, not a separate Wacom stack.

### Wi-Fi and Bluetooth

Wi-Fi is the `kiwi_v2` SKU: 85 files under `vendor_firmware_mnt/image/kiwi/`,
including `amss.bin` (7 458 880) and `amss20.bin` (6 422 592) plus the `bdwlan.e*`
board-data set (~88 KB each).

The chip family is WCN7850-class — `icnss2.ko` contains `qca6750`, `wcn6450`,
`wcn6750` identifiers, and the version file says
`WLAN.HMT.2.0-02195-QCAHMTSWPL_V1.0_V2.0_SILICONZ-2`. On Linux this is **ath12k**,
and the hard part is converting `bdwlan.*` into a `board-2.bin` that matches this
board's ID.

Bluetooth is HAMILTON (`BTFM.HAMILTON.2.0.1-00312-PATCHZ-1`):

```
hmtbtfw10.tlv   91 308     hmtbtfw20.tlv   265 528
hmtnv20_Lapis.bin  9 492   <- the board-specific NVM, note the device codename
hmtnv10.bin      6 255     + a large hmtnv20.bXXX calibration set
```

Linux path: `btqca` driver, firmware under `/lib/firmware/qca/`.

### Camera

The interesting find is that the sensor modules are named for `lapis` and come in
**two hardware variants** (`lce` and `txd`), with different parts:

| Variant | Main | Front | Macro |
|---|---|---|---|
| `lapis_lce` | GC13A0 | GC13A2 | SC202CS |
| `lapis_txd` | OV13B10 | GC13A2 | — |

Each has a sensor `.so`, a `sensormodule` `.bin` (the module calibration) and a
`tuned` `.bin` (the IQ tuning data). On Linux there is CAMSS for raw Bayer capture,
but no CAMX/Titan ISP — so basic capture is feasible and ZUI-quality output is not.

### Audio

Two amplifier/codec families appear in the configs: `wcd9395` and `wsa883x`, with
`aw882xx_acf.bin` (5 216 B) as a smart-amp calibration. The `sku_pineapple` set
contains full mixer paths and resource manager XMLs for `cdp`, `mtp`, `qrd`, `aim`.

On Linux this means remoteproc ADSP + AudioReach, with the topology and mixer
routing derived from these XMLs. The Android HAL `.so` files cannot be reused, but
the *configuration* inside them is the useful part.

### DSP and other coprocessors

```
adsp/  cdsp/                    ADSP and CDSP images
CAMERA_ICP.elf    3 174 148     camera ICP firmware
evass.elf/mbn                   EVA / video subsystem
vpu20_2v, vpu30_2v, vpu33_4v    video processing units
goodixfp64.bXX                  fingerprint, TEE-loaded
```

### Sensors

Nine distinct chips, from the sensor registry filenames:

| Chip | Function |
|---|---|
| `icm4x6xx` | accelerometer + gyro (6-axis IMU) |
| `lsm6dso` | accelerometer + gyro (alternate IMU) |
| `mmc56x3x` | magnetometer |
| `qmc630x` | magnetometer (alternate) |
| `bu52053nvx` | **hall sensor** — folio attach / lid |
| `aw963xx` | SAR (proximity for radio power) |
| `ads610x` | dToF (time-of-flight, presence) |
| `stk3` / `tcs3` | ambient light / RGB |

Two IMU and two magnetometer options confirm the multi-SKU situation seen with the
panels: this model ships with more than one sensor BOM.

---

## 6. Storage and partition layout

Six LUNs (`gpt_main0..5.bin`, `rawprogram0..5.x`). Sizes from the package:

| LUN | Role |
|---|---|
| 0–3 | boot-critical and system partitions |
| 4 | **`abl_a`, `abl_b`, `devinfo`** — the ones that mattered |
| 5 | additional / user data area |

Largest images: `super_4.img` 11.3 GB, `super_3.img` 3.4 GB, `super_7.img` 1.45 GB.
Total image payload 17.67 GB across 40 `.img` files.

> **The `rawprogram*.x` and `patch*.x` files are encrypted.** Confirmed by reading
> `rawprogram4.x` directly: high-entropy binary, no XML, no plaintext. Only Lenovo's
> `Download.exe` can decode them — it carries the key. This is why the ABL offsets
> had to be derived from an older readable package rather than from the current one.

---

## 7. Driver notes for a Linux port

Condensed from the three READMEs that came out of the kit, plus what the modules
reveal.

### Folio keyboard

`lenovo_keyboard.ko` is a **UART** driver with GPIO wake lines — its symbols include
`uart_data_proc`, `uart_pack_data`, `uart_wake_gpio`, `uart_wake_irq`. So the pogo
pins carry a serial link, not USB or I²C. It also exposes sysfs attributes
(`lenovo_kb_attributes`, `lenovo_kb_capsled_work`) for caps lock LED and layout.

`hall_mod.ko` handles attach/detection via `bu52053nvx`.

Both need an out-of-tree port; the 6.1.112 modules will not load elsewhere.

### Touch and stylus

Novatek NT36532 over I²C, with pen support in the same driver. Mainline has Novatek
support but not for this panel variant; the practical route is the vendor driver
ported forward, plus the correct per-panel firmware (Tianma vs BOE).

Watch out: `goodix_ts.ko` exists in the same directory. On this device the
fingerprint is Goodix (`goodixfp64.mbn`, TEE) — do not confuse the two.

### Display

`msm_drm.ko` registers both panel strings. A port needs the panel init sequence and
DSC configuration from the vendor driver; there is no upstream DT for either panel.

### USB

Confirmed dual-role. From Android with root, `dumpsys usb`, port `port0`:

```
supported_modes        dual, audio_acc
role combinations      source+host and sink+device
controller             a600000.dwc3
```

So Type-C can host a stick under Android or Linux. It cannot under ABL — ABL is
USB device only, which is why a USB Live stick cannot be booted by the bootloader.

---

## 8. Summary table

| Subsystem | Part | Linux support today |
|---|---|---|
| SoC | SM8650 / pineapple / LANAI | good in mainline ≥ 6.12 |
| GPU | Adreno 750 (gen70900) | `drm/msm` + Mesa Freedreno/Turnip |
| Storage | UFS 4.0, 6 LUNs | `ufshc`, since ~6.8 |
| Display | dual-DSI 3K, NT36532 touch, Tianma or BOE | **needs vendor panel driver** |
| Touch/stylus | Novatek NT36532 + active pen | vendor driver, port forward |
| Keyboard | folio, UART + hall `bu52053nvx` | **needs out-of-tree port** |
| Fingerprint | Goodix, TEE | not supported |
| Wi-Fi | WCN7850-class, `kiwi_v2` | ath12k, **BDF conversion needed** |
| Bluetooth | HAMILTON, `hmtnv20_Lapis.bin` | `btqca` |
| Audio | WCD9395 / WSA883x, ADSP | AudioReach + topology from XML |
| Camera | GC13A0/OV13B10 + GC13A2 + SC202CS | CAMSS raw only, no ISP |
| Sensors | 9 chips incl. 2 IMUs, 2 mags | mostly mainline drivers |
| USB | DWC3, dual-role | mainline |

The two hardest items are display and folio keyboard. Everything else has a plausible
mainline path.
