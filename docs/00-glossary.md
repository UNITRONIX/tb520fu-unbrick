# Glossary

Every term used in this repository, in the order you are likely to meet it.

---

## Boot chain

**PBL** — *Primary Boot Loader*. The first code that runs on a Qualcomm SoC,
burned into on-chip ROM. It initialises the bare minimum, then loads XBL from
storage. Cannot be modified or replaced. This is what talks to you when the
device presents `05C6:9008` in a *clean* EDL state.

**SBL / XBL** — *Secondary / eXtensible Boot Loader*. The first stage held in
flash. XBL sets up DDR, storage and secure boot policy, then loads ABL. On this
tablet the XBL image is `xbl_s.melf` / `xbl_s_devprg_ns.melf`.

**ABL** — *Android Boot Loader*. Qualcomm's fork of UEFI/EDK2 that implements
`fastboot`, applies device-tree overlays, verifies boot images and hands control
to the kernel. It lives on partitions `abl_a` and `abl_b`. **These two partitions
are the corrupted ones.** Note that ABL is verified by XBL, not by Sahara.

**TZ** — *TrustZone*. The secure-world OS. On SM8650 the hypervisor is Gunyah,
which sits between ABL and the kernel on this platform.

**crashdump mode** — a degraded state where the SoC exposes `05C6:900E` and
offers a memory dump instead of a normal boot. Useful only as a way *into* EDL;
it is not EDL itself.

**EDL** — *Emergency Download mode*, Qualcomm's recovery mode. Presents
`05C6:9008` and speaks Sahara. Confusingly, the same "EDL" label gets applied to
`900E`, which is crashdump. In this repo EDL means `9008` only.

**Fastboot** — the flashing protocol implemented by ABL. Never reached on this
device, because ABL never runs to the point of offering it.

---

## Protocols

**Sahara** — the protocol PBL speaks in EDL. It transfers a *programmer* into RAM
and then jumps to it. Packet-based, little-endian, 32-bit fields. See
[`03-sahara-protocol.md`](03-sahara-protocol.md).

**Firehose** — the protocol the *programmer* speaks once it is running. XML-based
commands (`<configure>`, `<read>`, `<program>`), typically over the same USB
endpoint. This is what actually writes partitions. **Firehose never started on
this device.**

**programmer** — the payload Sahara uploads into RAM. Qualcomm calls it the
"firehose programmer" or PEP (Primary Emergency Programmer). On this platform it
is `xbl_s_devprg_ns.melf`, 1 569 028 B.

**Sahara NAK** — a negative acknowledgement with a numeric reason. Values
`0x01`–`0x28` are documented in the Qualcomm protocol. Anything above that is a
vendor extension. See the table in `03-sahara-protocol.md`.

---

## File formats

**melf** — *multi-image ELF*. An ELF32 container with a small wrapper and several
concatenated inner images. This is the only format this device's PBL accepts for
a programmer. See [`04-melf-format.md`](04-melf-format.md).

**MBN** — Qualcomm's signed image format. Qualcomm does not officially expand the
acronym; treat it as a name, not an abbreviation. An MBN is an ELF plus a "hash
segment" holding a header, per-segment hashes, a signature blob and a certificate
chain.

**hash segment** — the part of an MBN that makes verification possible. Contains
the hashes of each ELF segment, so the loader can check integrity without
re-reading the whole image.

**VIP** — *Verified Image Process*, a newer Qualcomm authentication scheme that
uses a "digest table" and, in some configurations, expects the programmer to be
accompanied by a separate `Digest.elf` / `Sign.bin`. The programmer on this device
contains VIP code paths, but no digest table was found in any Lenovo package.

**XBL config / `.x` files** — Lenovo's proprietary, encrypted content descriptors
used by their own flashing tools. `rawprogram0.x`, `patch0.x`, etc. They contain
the partition map and per-file metadata. We cannot decrypt them; the offsets used
here were obtained by other means.

---

## Verification

**AVB** — *Android Verified Boot*. Verifies boot/recovery/vbmeta images using the
`vbmeta` partition. Independent of Sahara.

**verified boot state** — reported as `green` (locked, stock), `yellow` (locked,
custom key), `orange` (unlocked), `red` (verification failed). This device is
`orange`.

**secure boot** — the SoC-level policy that decides which certificates are
trusted. On this device, XBL accepted an ABL signed with **qtestsign** test keys,
which tells us firmware secure boot is *not* enforcing a Lenovo-only root of trust
at that stage.

**qtestsign** — an open-source tool (GPL-2.0) that wraps an ELF in MBN format with
a stub signature and a dummy certificate chain. It does **not** create a real
signature. Works only where secure boot is disabled.

---

## Storage

**LUN** — *Logical Unit Number*. UFS exposes several LUNs, each with its own
address space and sector numbering. Both `abl` partitions on this device are on
**LUN 4**.

**UFS** — *Universal Flash Storage*. The eMMC successor; this tablet uses UFS 4.0.
Not eMMC, despite what some teardowns claim.

**sector** — 4096 bytes on this platform (not the historical 512).

**A/B (slots)** — two copies of the boot-critical partitions (`_a` and `_b`) so an
update can fail safely. This device currently boots slot `a`. Because **both**
slots received the wrong ABL, there is no fallback.

**slot-retry-count** — a per-slot counter in the `devinfo`/misc area; ABL decrements
it on failed boots and eventually marks the slot unbootable. Observed at 6 during
the failure sequence.

---

## Power and safety

**DBC** — *Dynamic Battery Check*. A guard inside the programmer: if battery
voltage is below `loader-dbc-threshold`, the programmer shuts the device down
instead of initialising storage. Strings for this are present in the melf.

**VBAT / VSYS** — battery and system rail voltages, in millivolts. Referenced by
the DBC configuration inside the programmer.

**pstore / ramoops** — a kernel mechanism that preserves the last kernel log in a
reserved memory region across a reboot. Used during the Linux bring-up to capture
logs from failed boots.

**DDR training** — the calibration sequence between the memory controller and the
DRAM chips. Must succeed before the programmer can do anything useful; runs
inside the fifth image of the melf.

---

## Things that are not what they look like

**"EDL cable"** — a USB cable with a resistor or a short between specific pins,
intended to force EDL. On this device it produced a genuine PBL-level EDL **once**,
and did not change the outcome. Subsequent attempts showed no effect.

**`DEVICE_DESCRIPTOR_FAILURE`** — a Windows placeholder for a USB device that
enumeration reached but which returned no descriptor (`VID_0000&PID_0002`). This
is **not** a hidden mode; it is a hung PBL, caused by replugging the cable
mid-negotiation.

**`prog_firehose_ddr.elf`** — looks like the Firehose programmer, and its code
*is* the Firehose programmer, but as a standalone file it is the wrong container.
The device rejects it after 64 bytes.

**`xbl_s.melf`** — a 1 117 008 B prefix of the full programmer. Everything up to
and including the Firehose image, without the DDR-training image. Useful for
tests, not for writing.

---

## Hardware and drivers

Part numbers and subsystem names. The full inventory, with file sizes and provenance,
is in [`13-hardware-and-drivers.md`](13-hardware-and-drivers.md).

**`lapis`** — the device codename for `TB520FU`. Appears in `getvar product`, DTB
filenames, sensor registry names (`lanai_*_lapis.json`) and the Bluetooth NVM file
`hmtnv20_Lapis.bin`. Three naming layers coexist in one filename there: `lanai`
(platform), `lapis` (device), `bu52053nvx` (chip).

**`pineapple`** — Qualcomm's platform codename for SM8650. Used in kernel module
names (`debugcc-pineapple.ko`), audio configs (`mixer_paths_pineapple_*.xml`) and
upstream Linux.

**`LANAI`** — Qualcomm's build/target name for this board family, used in every
firmware version string (`BOOT.MXF.2.1-...-LANAI-1`, `TZ.XF.5.28-...`). Count in
`ver_info.txt`: 22 occurrences of `LANAI`, zero of `pineapple`. Both names are
correct; searching only one finds half the files.

**GKI** — *Generic Kernel Image*. Android's kernel/module split where the kernel is
built generically and vendor code ships as loadable modules against an exact version.
This device is **6.1.112-android14-11**. The consequence that matters: a module built
for that version loads nowhere else, so a Linux port cannot reuse these `.ko` files.

**DLKM** — *Dynamic Loadable Kernel Modules*. Two partitions here:
`system_dlkm` (60 modules) and `vendor_dlkm` (280 modules).

**`init_boot`** — on a GKI device with boot header v4, the partition that holds the
**generic ramdisk**, while `boot` holds the kernel. Measured on this device:
`boot.img` has `kernel_size 35 289 600` and `ramdisk_size 0`; `init_boot.img` has
`kernel_size 0` and `ramdisk_size 2 099 409`. This is why Magisk is patched into
`init_boot` and patching `boot` does nothing useful.

**`header_version 4`** — the boot image header revision. `header_size` 1584. Determines
which `mkbootimg`/`unpack_bootimg` options apply.

**DSC** — *Display Stream Compression*. The panels use it (`lapis_tianma_nt36532_dsc_3k_video`),
which is why a naive panel port produces a black screen rather than a wrong picture.

**NT36532** — the Novatek touch controller part number. Both panel variants use it.
Handles the active stylus as well as fingers — there is no separate Wacom stack.

**`nvt_36xxx.ko` / `nt36xxx-i2c.ko`** — the Novatek driver, in two transport variants.
Carries pen support (`nvt_pen_max_pressure`, `pen_2d_raw_tip_x`).

**`goodix_ts.ko` vs `goodixfp64.mbn`** — touch versus fingerprint. Different silicon,
both Goodix, easy to confuse. The fingerprint runs in TEE and has no Linux support.

**`lenovo_keyboard.ko`** — the folio keyboard driver. It is a **UART** driver with
GPIO wake lines (`uart_pack_data`, `uart_wake_gpio`), not USB or I²C. The pogo pins
carry a serial link.

**`bu52053nvx`** — the hall sensor chip. Drives folio attach and lid detection, via
`hall_mod.ko`.

**`kiwi_v2`** — the Wi-Fi firmware SKU. 85 files under `vendor_firmware_mnt/image/kiwi/`,
including `amss.bin`, `amss20.bin` and the `bdwlan.e*` board-data set.

**WCN7850 / QCA6750** — the Wi-Fi chip family. `icnss2.ko` references `qca6750`,
`wcn6450`, `wcn6750`. On Linux this is **ath12k**, and the hard part is converting
`bdwlan.*` into a matching `board-2.bin`.

**HAMILTON / HMT** — the Bluetooth firmware family (`BTFM.HAMILTON.2.0.1`).
Files: `hmtbtfw10.tlv`, `hmtbtfw20.tlv`, and the board NVM `hmtnv20_Lapis.bin`.

**EVA** — the video encode/decode subsystem (`msm-eva.ko`, `evass.elf`). Separate
from the camera ISP.

**ICP** — *Image Capture Processor*, part of the camera pipeline (`CAMERA_ICP.elf`).

**CAMSS vs CAMX** — CAMSS is the mainline Linux camera subsystem (CSI/VFE, raw Bayer).
CAMX is Qualcomm's Android camera stack with the Titan ISP. Linux gets CAMSS only.

**`gen70900`** — the Adreno 750 firmware family: `gen70900_sqe.fw`, `gen70900_aqe.fw`,
`gmu_gen70900.bin`, `gen70900_zap.mbn`. The numbers are a firmware generation, not a
part number.

**FBE** — *File-Based Encryption*. `/data` is encrypted per-file with keys unlocked at
boot. A cold-boot custom initramfs cannot mount it, which is why "Fedora on `/data`"
failed regardless of the pivot's correctness.

**inlinecrypt** — the f2fs feature implementing FBE on this device. Relevant because it
is invisible from the host and only shows up when a custom pivot tries to mount `/data`.
