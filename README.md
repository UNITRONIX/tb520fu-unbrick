# tb520fu-unbrick

Field notes, tooling and a post-mortem from an attempt to recover a **Lenovo Yoga
Tab Plus** (`TB520FU`, codename **lapis**, Snapdragon 8 Gen 3 / **SM8650**) that was
soft-bricked while switching its bootloader for a Linux port.

**Outcome: the software route is exhausted.** The tablet accepts the factory
programmer, then never starts it. Every layer on the host side was measured,
fixed and proven working; the blocker sits inside the device and cannot be moved
without a service-level EDL access (test point) or Qualcomm's signing keys.

This repository exists so that the next person with the same tablet does not
spend two weeks rediscovering the same dead ends.

---

## TL;DR

| Question | Answer |
|---|---|
| What is broken? | The contents of `abl_a` and `abl_b` (both 1 MiB, LUN 4). Hardware and everything below the bootloader are fine. |
| Can it be fixed over USB from a PC? | **No.** Not with QFIL, `fh_loader`, `edl`, LTBox, custom libusb code, Windows or native Linux. |
| Why? | Sahara accepts the signed programmer (full transfer, `END 0x0`, `DONE`), but the programmer never comes up as a Firehose endpoint. The device disappears from USB about 8 s later and returns in crashdump mode. |
| Is it a cable/driver/OS problem? | No. Four independent tools and two operating systems produce the identical result. |
| Is it a signature problem? | No. The *original* Lenovo programmer already passes; a self-signed one fails for a different, well-understood reason (format, not crypto). |
| Is it a battery problem? | No. Ruled out with a full 9-hour charge and a clean control run. |
| What is left? | Test-point EDL (opens the case, voids warranty) or Lenovo service. |

---

## The device

| | |
|---|---|
| Marketing name | Lenovo Yoga Tab Plus / YOGA Pad Pro 12.7 AI |
| Model | `TB520FU` |
| Codename | `lapis` |
| SoC | Qualcomm **SM8650** ("pineapple") — Snapdragon 8 Gen 3 |
| GPU | Adreno 750 |
| Storage | UFS 4.0 |
| Last known good OS | Android 16, ZUI 18.5.10.037 lineage |
| Bootloader | unlocked, verified boot `orange` |
| Partition layout | A/B, current slot `a` |

> **Note on the SoC.** Some early community write-ups list `TB520FU` as a MediaTek
> Helio G99 device. That is wrong for this unit. Everything in this repository
> assumes Qualcomm SM8650 and the Qualcomm Sahara/Firehose stack.

---

## What actually happened

1. The tablet was unlocked (official Lenovo `sn.img` unlock) and rooted with
   Magisk on `init_boot`, which is the correct partition on GKI devices.
2. A custom pivot initramfs was built to try booting Fedora from a USB stick.
   The fallback path to normal Android was broken, so booting without the stick
   hung on the Lenovo logo.
3. To get a bootloader that could load a Linux kernel, a **ROCKNIX ABL**
   (built for SM8650 handhelds — AYANEO Pocket S2 / KONKR, *not* for this tablet)
   was flashed to **both** `abl_a` and `abl_b`.
4. That ABL boots, but reads its volume keys from GPIOs that do not exist on this
   board. Its menu is therefore unreachable, and it does not hand off to Android.
   Result: logo → Qualcomm crashdump (`05C6:900E`) → reset → repeat.
5. Recovery was then attempted exclusively over EDL. That is the subject of this
   repository.

---

## What we proved works

Everything below was measured, not assumed.

| Layer | Status | Evidence |
|---|---|---|
| USB enumeration of EDL | works | `05C6:9008` and `05C6:900E` both reached |
| Crashdump → real EDL bump (`900E`→`9008`) | works | repeatable mode-switch sequence |
| Sahara handshake | works | `HELLO ver=3 mode=0` straight from PBL |
| Sahara image upload | works | 1 554 996 B of 1 569 028 B transferred, `high_water` covers the whole payload |
| Sahara packet framing | works | strict framing, multiple packets per `read()` handled |
| Zero-length packet (ZLP) handling | works | added for 512-byte-aligned chunks |
| Programmer integrity check | passes | `END status=0x0` with the factory programmer |
| `DONE` handshake | works | `DONE_RSP cmd=0x6` |
| `SAHARA_RESET` (`0x07`) | works | returns `RESET_RSP` |

## What never worked

| Layer | Status | Evidence |
|---|---|---|
| Firehose `configure` | dead | silence on every XML variant, in every session |
| Firehose `nop` | dead | silence, including re-opened handles |
| Firehose endpoint re-enumeration | never happens | device leaves USB ~8 s after `DONE` |
| Fastboot | never reached | ABL never hands off |
| ABL menu keys | unread | GPIO mapping is for a different board |
| Standalone `prog_firehose_ddr.elf` | `0x29` after 64 B | rejected on the ELF header, before any signature check |
| Self-signed programmer | `0x29` same as unsigned | format rejection, not a crypto rejection |
| Firehose image substituted inside the melf | `0x21` | the whole blob is hashed, not per-image |
| Test point EDL | not attempted | requires opening the case |

---

## Why it failed — the three layers

The problem is not one thing. There are three stacked barriers, and they are all
in the wrong place to be useful:

1. **Format.** This PBL only accepts a `melf` — an ELF32 container holding five
   images, one of which *is* the Firehose programmer. A plain ELF64
   `prog_firehose_ddr.elf` is rejected after 64 bytes with `0x29`, a code that
   does not exist in the published Sahara table (it is a vendor NAK).
2. **Integrity.** Modifying any image inside the melf fails with `0x21`
   (`HASH_TABLE_AUTH_FAILURE`). The transfer dies at byte 1 109 804, which is
   *before* the replaced Firehose image at 1 117 008 — proving the check covers
   the entire blob, not the individual images. No per-image digest is stored in the
   file under any standard algorithm we tested.
3. **Runtime.** With the untouched factory programmer, all three earlier layers
   pass and `DONE` is acknowledged — and then nothing. The programmer is accepted
   but never binds Firehose to USB.

Layers 1 and 2 are solved by using the original file from the Lenovo package.
Layer 3 is the wall.

---

## Where the write blocker is

The device is not stuck in Sahara — it is stuck *after* Sahara. The observed
timeline for one cycle:

```
logo (0 s)  →  USB absent, ~15 s, measured at 0.15 ms resolution
            →  05C6:900E crashdump  (bump)  →  05C6:9008
            →  Sahara HELLO ver=3 mode=0
            →  upload 1 554 996 B  →  END 0x0  →  DONE
            →  <configure/> sent 1 ms later
            →  silence
            →  device gone from USB ~8 s after DONE
            →  back to 05C6:900E
```

Two explanations remain, and both are on the device side:

- The programmer dies during hardware init (DDR training or UFS), which the melf
  itself suggests — it contains `sbl1_ddr_init`, `do_ddr_training`,
  `Entering DeviceProg DDR`.
- The programmer is shut down by its own battery guard (DBC). The melf contains
  `loader-dbc-threshold`, `skip-loader-dbc`, `vbatt-min`,
  `charger is not charging and device will shut down`. A 9-hour charge ruled out
  low voltage as the *cause of earlier instability*, but not as a shutdown path.

Because the programmer never speaks, we cannot tell these apart from the host.

---

## Good news for whoever fixes it

The repair itself is trivial. The correct payloads are known and verified:

| Partition | LUN | Start sector | Sectors | Size | Image |
|---|---|---|---|---|---|
| `abl_a` | 4 | 95238 | 256 × 4096 B | 1 MiB | ABL from ZUI 17.5.10.096 |
| `abl_b` | 4 | 437686 | 256 × 4096 B | 1 MiB | ABL from ZUI 18.5.10.037 |

```
stock_abl_a.img  sha256 = 4E13E55EC9BFE814404F5E7E71451263F9A3BF7A5B09F495DD40FE6D96822EB7
stock_abl_b.img  sha256 = 2E3D51734AD16F258AA9979BBA0B33AF2164E40040750C1FFF59D8184DB5DEB0
```

Two 1 MiB writes. Everything else in this repository was the road to obtaining
permission to perform them. See
[`docs/09-service-report.md`](docs/09-service-report.md) for the report handed to
the service centre.

---

## Repository map

```
README.md                     you are here
docs/
  README.md                   index and reading order
  00-glossary.md              every acronym, explained
  01-timeline.md              what happened, in order
  02-device-and-partitions.md partition table, slots, ABL facts
  03-sahara-protocol.md       the protocol, as measured on this device
  04-melf-format.md           the five-image container, dissected
  05-firehose-and-the-silence.md   the wall
  06-signing.md               qtestsign, what it does, why it did not help
  07-dead-ends.md             everything tried that did not work, and why
  08-linux-port-notes.md      Fedora / mainline bring-up notes
  09-service-report.md        report submitted to the repair centre
  10-hardware-notes.md        the ROCKNIX ABL substitution analysis
  11-faq.md                   short answers to the obvious questions
session-notes/                raw translated session logs, unedited
scripts/                      the tooling, in English, path-parameterised
```

Start with [`docs/README.md`](docs/README.md) — it tells you which document to
read depending on what you are trying to do.

---

## A warning before you run anything

- Flashing the wrong ABL, or an ABL built for a different board, is exactly how
  this tablet got here. Do not flash `ROCKNIX` ABL to a `TB520FU`. It boots, it
  has no working keys, and it does not hand off to Android.
- Do not alternate between Qualcomm COM drivers (`qcser`/`qcusbser`) and WinUSB
  in one session and expect `fh_loader` to work. They are mutually exclusive
  worlds. Pick one.
- Do not send `SAHARA_RESET_STATE_MACHINE` (`0x13`). It kills the pipe. Use
  `SAHARA_RESET` (`0x07`).
- Do not trust `END status=0x0` alone. In `mode=2`, the device will happily
  acknowledge a **zero-byte** transfer. Require `bytes >= payload size`.
- Do not run recovery attempts on a low battery. Every interrupted session leaves
  the device wedged and deepens the cycle.

---

## Scripts

All scripts are standalone, take explicit paths, and print English logs. See
[`scripts/README.md`](scripts/README.md).

| Script | Purpose |
|---|---|
| `melf_tool.py` | inspect, split, patch and verify a `melf` container |
| `analyze_melf_map.py` | map data regions, compare embedded Firehose with the standalone ELF |
| `find_hashes.py` | hunt for per-image hashes inside the container |
| `build_signed_melf.py` | rebuild a melf with a substituted image |
| `sahara_upload.py` | strict-framing raw-libusb Sahara uploader |
| `banner_capture.py` | upload, then **listen** instead of talking |
| `sahara_codes.py` | the NAK table, with the vendor range marked |
| `usb_watch/FastUsbWatch.cs` | 0.15 ms USB presence watcher, no WMI, no sleeps |

---

## Redaction

Device serial numbers, USB instance paths and local user directory names have
been removed from every published note. Where a value was operationally relevant
it is replaced with `<DEVICE_SERIAL>`, `<HOST_USER>` or a generic path. The
hardware ID `0x2280e1` is kept: it identifies the platform, not the unit.

---

## Licence

GPL-3.0 (see `LICENSE`).

Third-party material is referenced, never vendored:

- [`bkerler/edl`](https://github.com/bkerler/edl) — GPL-3.0, the `edlclient`
  library used in some captures.
- [`obbardc/qtestsign`](https://github.com/obbardc/qtestsign) — GPL-2.0. Note
  that qtestsign **generates no real signature** and works only where firmware
  secure boot is disabled.
- Lenovo RSA firmware packages — proprietary, not redistributed here. Obtain
  them from Lenovo yourself; the SHA-256 of the two relevant payloads is
  published above so you can confirm you have the right ones.

No Lenovo firmware, no Qualcomm programmer, and no signing material is included
in this repository.

---

## Contributions

If you own a `TB520FU` in this exact state and you have access to a test point,
or you have seen the Firehose endpoint appear on this platform, please open an
issue. Specifically interesting:

- a `.melf` or programmer for SM8650 Lenovo that gets past `DONE` with a live
  Firehose endpoint,
- a UART or pstore capture from a boot attempt,
- confirmation of which of the two shutdown hypotheses is true.

Read [`docs/11-faq.md`](docs/11-faq.md) first — it may already answer your
question.
