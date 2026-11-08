# Linux port notes (the work that came before the brick)

These are the notes from the Fedora / mainline effort. They are included because
they document the device thoroughly, and because the pivot initramfs is what
started the chain of events that ended in the brick.

**Nothing here was ever booted successfully.** No mainline kernel, no Fedora
userspace, no working display. Treat all of it as unfinished work, not as a guide.

---

## 1. State before the brick

| Item | State |
|---|---|
| Bootloader | unlocked, verified boot `orange` |
| Root | Magisk 30.7, patched into `init_boot` (GKI — not `boot`) |
| Android | 16, ZUI 17.5.10.096 lineage |
| Stock images | `boot`, `init_boot`, `recovery` extracted from the RSA package |
| Kit | ~480 MB of firmware, DLKM modules and vendor HALs pulled with root |

Verified root:

```
adb shell /debug_ramdisk/magisk su -c id
uid=0(root) gid=0(root) context=u:r:magisk:s0
```

---

## 2. Why the pivot failed

The goal was to boot Fedora from a USB stick without touching `boot`. The plan was
a custom `init_boot` whose first stage mounts an ext4 image from the stick and
pivots into it, falling back to Android if the stick is absent.

Two bugs, both fatal:

### Bug 1 — internal storage looks like USB

The pivot scanned `/dev/sda*` and `/dev/sdb*`. On this platform **internal UFS
enumerates as `sd[a-f]`**. So `sda` was internal userdata, not the stick. The pivot
mounted internal volumes as if they were the root, and blocked before the fallback
could ever run.

The fix (`removable=1` filter) was correct but applied to an image that was already
bricking the no-USB path.

### Bug 2 — the Android fallback never worked

The fallback was designed as: on timeout, `exec /init.android` (the stock first
stage, embedded in the ramdisk at ~648 KB). Even with the scan fixed and the image
rebuilt at 2.37 MiB — comfortably inside the 8 MiB `init_boot` — booting without
the stick still hung on the logo, with no ADB, no fastboot and no recovery.

Probable cause for anyone continuing this work: the stock first stage expects to be
PID 1 and to own the early mount namespace. `exec`-ing it from a pivot that has
already mounted things gives it an inconsistent environment, and it fails silently.
A correct approach is likely a Magisk-style ELF wrapper that hands off before any
mounting occurs, or a chainload that restores the original initramfs layout.

### Size facts worth remembering

| Partition | Real size | A wrong assumption that circulated |
|---|---|---|
| `init_boot` | **8 MiB** (`0x800000`) | 96 MiB |
| `boot` | larger, but untouched throughout | — |

Flashing a 96 MiB image to an 8 MiB partition is not survivable. Check the
partition size from the GPT before flashing anything.

---

## 3. `fastboot boot` results (RAM only, nothing flashed)

The one genuinely encouraging result, from before the brick.

### Attempt 1 — stock kernel, empty ramdisk (format control)

```
Sending 'boot.img' (34468 KB)     OKAY [  0.787s]
Booting                           OKAY [ 10.156s]
fastboot_exit=0
post_mode=adb ... <DEVICE_SERIAL> device
```

**Success.** ABL accepted a boot image built with the custom packer
(`header_version=4`, `header_size=1584`, `page_size=4096`, kernel at `0x1000`).
This proves the boot image construction was correct — an important control, and
the reason the next failure could be attributed to the kernel rather than the
packaging.

### Attempt 2 — Fedora Live kernel + stock FDT + Fedora Live initrd

```
Sending 'boot.img' (357064 KB)    OKAY [  8.145s]
Booting                           OKAY [ 10.199s]
fastboot_exit=0
post_mode=unknown (no adb, no fastboot)
```

ABL did **not** reject the image — no fastboot error, `Booting OKAY`. The device
then dropped off USB and did not return within 90 s.

**Interpretation:** the kernel started and hung or crashed very early. Not an ABL
parse failure.

### Why it hung (three compounding reasons)

1. **Generic kernel, no board support.** The Fedora aarch64 kernel has no
   `TB520FU` device tree and no `pineapple` board bring-up. Clocks, regulators,
   UFS and display are all wrong or absent.
2. **Stock FDT is an Android FDT.** The DTB read from `/sys/firmware/fdt` describes
   GKI 6.1 bindings, not what a 7.x mainline kernel expects.
3. **Live initrd expects LiveOS media.** It looks for `LiveOS/squashfs.img` on a
   mountable medium. Even if the kernel had lived, root would have failed.

Attempts 3–5 (earlycon, no-DTB, stock-kernel-plus-Fedora-initrd) were prepared but
never run — the device did not come back to fastboot without manual intervention.

---

## 4. Mainline kernel status (research, late 2025 / early 2026)

| Topic | Finding |
|---|---|
| SoC enablement | SM8650 ("pineapple") patches posted by Linaro around Oct 2023; QRD DT Nov 2023 |
| Merge window | core platform in the 6.7–6.8 era, maturing through 6.12 LTS |
| GPU | `drm/msm` Adreno 750 + GMU, in mainline with QRD enablement |
| Display | DSI with DSC on later trees; DP alt-mode on reference boards |
| Storage | UFS (UFSHC) from ~6.8 |
| USB | DWC3 + Type-C/PD, PMIC GLINK on recent kernels |
| Wi-Fi | ath12k, WCN7850-class — board BDF is device-specific |
| Board DT for TB520FU | **none upstream**; only `sm8650-qrd`, `sm8650-mtp`, HDK |
| Community DT | a `linux-tb520fu` tree documents `sm8650-lenovo-tb520fu(.boe).dtb`, untested on hardware |

Build environment used: WSL2 Ubuntu 22.04, `aarch64-linux-gnu-gcc`, targeting
Linux 6.12 stable with `sm8650-qrd.dtb` as a first silicon-bring-up DTB.

**The QRD DT will not boot this tablet.** It is the right silicon and the wrong
board: display, regulators and storage wiring differ. It is only useful to prove
the kernel can start at all.

---

## 5. Firmware map (for a future port)

Useful because collecting these blobs is tedious and they are all present on the
stock device.

### GPU

```
vendor_firmware/gen70900_sqe.fw
vendor_firmware/gen70900_aqe.fw
vendor_firmware/gmu_gen70900.bin
vendor_firmware/gen70900_zap.mbn
```

Install under `/lib/firmware/qcom/`. Kernel side is `drm/msm` + GMU; userspace is
Mesa Freedreno and Turnip. The proprietary Adreno userspace blobs
(`libEGL_adreno.so`, `vulkan.adreno.so`, …) are **Android-only** — do not try to
load them on glibc Fedora.

### Wi-Fi

```
vendor_firmware_mnt/image/kiwi/    amss.bin, amss20.bin, bdwlan.e*  (~85 files)
```

Linux wants ath12k with a `board-2.bin` built from the `bdwlan` set. The known
pain point is board-id matching on SM8650.

### Bluetooth

```
vendor_bt_firmware/image/   hmtbtfw10.tlv, hmtbtfw20.tlv, hmtnv20_Lapis.bin
```

Mainline `btqca`, HMT firmware under `/lib/firmware/qca/`. Note
`hmtnv20_Lapis.bin` — the filename confirms the codename.

### Audio

```
vendor_dsp/adsp, vendor_dsp/cdsp
vendor_firmware_mnt/image/adsp*.mdt, adsp*b*
vendor_libs/audio/*.so + topology XML
```

Linux path is remoteproc ADSP + AudioReach/q6apm. The Android HALs cannot run on
Fedora; what you extract from them is the *graph and mixer configuration*, plus the
DSP ELF.

### Input

```
drivers/input/keyboard_folio/    lenovo_keyboard.ko, hall_mod.ko
drivers/input/stylus_touch_novatek/  nvt_36xxx.ko, nt36xxx-i2c.ko, goodix_ts.ko
                                     novatek_ts_tianma_fw.bin, novatek_ts_boe_fw.bin
```

The folio keyboard driver needs an out-of-tree port against mainline — the stock
`.ko` is GKI 6.1 and will not load. Both panel firmwares must ship because there
are two panel variants (Tianma and BOE).

Do not confuse `goodix_ts.ko` (touch) with `goodixfp64.mbn` (fingerprint, runs in
TEE).

### Camera

Feasible but limited: mainline CAMSS gives you CSI/VFE raw Bayer, and libcamera can
drive it. There is no CAMX/Titan ISP on Linux, so full ZUI-quality capture is not
realistic.

---

## 6. Fedora packaging attempt

- Base: Fedora 45 KDE Plasma Desktop Live, aarch64, ~3.54 GiB, SHA-256 verified.
- A minimal rootfs (~272 MB) was built and placed on the device at
  `/data/tb520fu_fedora`.
- A 512 MiB ext4 image containing it was created on a Ventoy stick as
  `tb520fu_fedora.ext4`.

**Blocked by FBE.** `/data` is file-based encrypted (`inlinecrypt` on f2fs). A cold
pivot cannot mount it, so "Fedora from `/data`" is not viable. The only workable
direction was an unencrypted rootfs on USB OTG — which is what the broken pivot was
trying to do.

Alternative that was considered and not pursued: install the rootfs to a spare UFS
LUN or a userdata subvolume while Android is healthy, avoiding FBE entirely.

---

## 7. USB host capability (confirmed)

From Android with root, `dumpsys usb`, port `port0`:

| Property | Value |
|---|---|
| `supported_modes` | `dual`, `audio_acc` |
| Role combinations | `source+host` and `sink+device` |
| When connected to a PC | `ufp` / sink / device |
| Controller | `a600000.dwc3` |

So the Type-C port **can** act as USB host under Android or Linux. It cannot do so
under ABL — ABL implements USB device mode only, for fastboot. This distinction is
the reason a USB Live stick cannot be booted by ABL.

There is a single physical Type-C port, so host and device roles cannot be used
simultaneously without an awkward dual-role hub. Plan workflows accordingly
(`adb push` versus OTG copy).

---

## 8. TWRP assessment (conclusion: not worth it)

| Candidate | Verdict |
|---|---|
| Dedicated `TB520FU` TWRP | none maintained |
| A repo named for `TB520FU` / Yoga Pad Pro | contents track Y700 `TB321FU` — not a real `lapis` port |
| `polygraphene` `TB321FU` TWRP 3.7.1 | working, same SM8650, **different panel, partitions and layout** — good template, not drop-in |
| Official twrp.me | no listing |

A port needs a new device tree, dual-DSI+DSC panel init, Novatek in recovery, FBE
decrypt patches, and a header-v4 recovery image. Multi-day work, with the largest
risk being display and touch.

And it does not help the Fedora effort: `fastboot boot`, Magisk `adb` and EDL
already cover install and rescue. Recommendation was to defer TWRP until after the
kernel boots.

---

## 9. What killed it

Not the kernel work. The pivot initramfs bricked `init_boot`, and the attempt to
work around that — swapping ABL for a handheld build — bricked both ABL slots.

For anyone continuing on a *healthy* `TB520FU`:

1. Never flash a speculative `init_boot`. Test with `fastboot boot` first, always.
2. Build the mainline kernel and TB520FU DTB before touching the pivot at all.
3. Keep one ABL slot stock. Always. The A/B scheme is your only safety net.
4. Do not flash a bootloader built for other hardware, however similar the SoC.

Those four rules would have prevented everything in this repository.
