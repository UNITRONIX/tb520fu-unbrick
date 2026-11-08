# Timeline

Dated, in order, with the device state at the end of each phase. Where an
original note was written in Polish, the source is in
[`session-notes/`](../session-notes/) and the filename is given.

All dates are 2026. Local time was UTC+1.

---

## Phase 1 — 3 November: unlock, root, first Linux attempts

**Starting state:** Android 16, bootloader unlockable, warranty intact.

1. Unlocked the bootloader with the official Lenovo unlock file
   `sn.img`, obtained from `zui.com/iunlock` for this specific serial. Note this
   is *not* `fastboot flashing unlock` — Lenovo gates it per-unit. Unlocking wipes
   userdata, as expected.
2. Confirmed `ro.boot.flash.locked=0`, verified boot `orange`.
3. Extracted stock `boot.img`, `init_boot.img`, `recovery.img` from the ZUI
   17.5.10.096 RSA package.
4. Rooted with **Magisk 30.7**, patched into **`init_boot`** (not `boot` — this is
   a GKI device, the ramdisk lives in `init_boot`). Verified with
   `su -c id` → `uid=0`, SELinux context `u:r:magisk:s0`.
5. Pulled ~480 MB of firmware, DLKM modules and vendor HALs to the PC as a reference
   kit.

**Then the first mistake:** a custom pivot initramfs was built to try booting
Fedora from a USB stick, and it was flashed to `init_boot`.

Two bugs compounded:

- The pivot scanned `/dev/sda*` and `/dev/sdb*` for the USB stick. On this
  platform **internal UFS already appears as `sda`–`sdf`**, so the pivot mounted
  internal volumes as if they were the stick, and blocked before the Android
  fallback could run.
- The fallback itself (`exec /init.android`) never worked, even after the scan was
  restricted to `removable=1` devices.

Result: booting without the USB stick hung on the Lenovo logo, with no ADB, no
fastboot and no recovery. `slot-retry-count` for slot `a` was observed at 6.

State at end of phase: **`init_boot` held a broken pivot; Android would not boot.**
This was recoverable — `boot` was untouched, and stock `init_boot` was on disk.

Source: `session-notes/2026-11-03-session-summary.md`.

---

## Phase 2 — 5 November: the ROCKNIX ABL decision

**The idea.** Rather than fix the pivot, replace ABL with one that can boot a Linux
kernel directly. `ROCKNIX` publishes a signed `abl_signed-SM8650.elf` for SM8650
handhelds.

**What was known at the time, and written down in the manifest:**

> `WARNING=ROCKNIX ABL is for SM8650 handhelds (AYANEO Pocket S2 / KONKR), not
> officially TB520FU/lapis.`

The warning was correct and was ignored. The ABL was flashed to **both** `abl_a`
and `abl_b`.

**What happened.** The ROCKNIX ABL boots — the tablet displays its loading screen.
But it reads its volume keys from GPIOs that do not exist on this board (AYANEO
hardware), so its menu is unreachable. It does not hand off to Android either.
The boot sequence became:

```
Lenovo logo → Qualcomm crashdump (05C6:900E) → reset → repeat
```

Because both slots were overwritten, there is no good slot to fall back to.

State at end of phase: **soft bricked.** `abl_a` and `abl_b` both contain a
bootloader built for different hardware.

Source: `session-notes/2026-11-05-manifest.md`,
`session-notes/2026-11-06-evening.md`.

---

## Phase 3 — 6 to 7 November: three gates, all failing at the same point

The goal became narrow and concrete: restore `stock_abl_a.img` and
`stock_abl_b.img` over EDL. Three independent toolchains were tried, called
"gates".

### Gate 0 — `bkerler/edl`, atomic

Bump `900E`→`9008`, then `edl printgpt --memory=ufs --lun=4`.

- Sahara: `Loader successfully uploaded`, ver 3, HWID `0x2280e1`.
- Firehose: `USBError` on the configure step; traceback inside
  `firehose.configure`.

**Fail.**

### Gate 1 — `QSaharaServer.exe` + `fh_loader.exe` (Lenovo's own tools)

- Requires a COM port. All `oem*.inf` files on the host mapped `05C6:9008` and
  `900E` to WinUSB, not to a serial port, so there was nothing for these tools to
  open. Fixed by binding the Qualcomm serial driver.
- Sahara: `Sahara protocol completed`, rc=0.
- `fh_loader`: `Failed to open com port \\.\COM5` after ~9 s. By then the device
  had already gone to the logo and returned as `900E`.

**Fail** — identical pattern.

### Gate 2 — LTBox

- Connected, EDL confirmed, loader accepted.
- `Firehose: configuring` → `Firehose read failed: os error 995` (I/O aborted) →
  `EDL session open failed`.

**Fail** — identical pattern.

### Also tried: native Linux

A second host running native Ubuntu, with the same `edlclient`, produced
`USBError(19)` immediately after `DONE`. Two different programmers (from ZUI
17.5.10.096 and 18.5.10.037, different hashes) behaved identically.

**Conclusion at this point:** the problem is not the host, not the OS, and not the
choice of tool.

State at end of phase: **all mainstream EDL paths exhausted.**

Source: `session-notes/2026-11-06-evening.md`,
`session-notes/2026-11-07-linux-gate.md`.

---

## Phase 4 — 7 to 8 November: protocol-level work

Reasoning: if every off-the-shelf tool fails at the same byte, the tool is not the
problem — our understanding of the protocol is. So the protocol was reimplemented
from scratch on raw libusb.

Findings, in the order they were made:

1. **`0x13` was poisoning sessions.** Early scripts used
   `SAHARA_RESET_STATE_MACHINE` (`0x13`) as a "safe reset". It kills the pipe.
   `SAHARA_RESET` (`0x07`) is the correct call and returns `RESET_RSP`.
2. **Packet framing was wrong.** `read()` on the bulk endpoint returns however many
   bytes are available, which can be *several* Sahara packets. The scripts parsed
   only the first header and discarded the rest, desynchronising the session and
   producing `0xD` (`NAK_READ_DATA_ERROR`). Fixed with a byte buffer that always
   consumes exactly `length` from the header.
3. **`edlclient`'s `usb_class` does not work on this host** (`Permission denied`),
   but raw libusb does, once `set_configuration(1)` and `claim_interface(0)` are
   called explicitly.
4. **Orphaned processes held the USB handle.** Four leftover `python.exe`
   processes from a previous session blocked all access. This alone accounted for
   hours of confusing failures.
5. **The melf is a container of five images**, and the fifth is DDR training.
   The standalone `prog_firehose_ddr.elf` is *bit-identical* to inner image 3.
   See [`04-melf-format.md`](04-melf-format.md).

State at end of phase: **the transport works perfectly.** Full 1 554 996 B, strict
framing, `END 0x0`, `DONE` acknowledged, on demand and repeatably.

Source: `session-notes/2026-11-07-night.md`,
`session-notes/2026-11-08-morning.md`.

---

## Phase 5 — 8 November: testing every remaining hypothesis

With transport solved, the remaining candidates were tested one at a time.

| Hypothesis | Method | Result |
|---|---|---|
| Battery too low (DBC shutdown) | 9 h on mains charger, then a clean control run | **Excluded as cause of instability** — clean cycle after charging. Not excluded as a shutdown path for the programmer. |
| Signature is the blocker | `qtestsign`-signed Firehose, three variants (v7, v6, same-size) | **Excluded** — all return `0x29` after 64 bytes, same as unsigned. Format rejection, before any signature check. |
| Wrong image inside the melf | Substituted signed Firehose, preserved every offset | **Excluded** — `0x21`, transfer dies at 1 109 804, *before* the swapped image. Whole-blob integrity check. |
| Hash is computed and stored in the file | SHA-256 and MD5 of every image searched across the whole blob | **Excluded** — no hash is present in recoverable form. |
| `DONE` is optional | Four variants of post-`END` behaviour | **Excluded** — without `DONE` the device stays in Sahara and answers `END status=0xD`. |
| `END 0x0` with zero bytes is a success | Discovered by accident | **Wrong, and dangerous** — device acknowledges a zero-byte transfer in `mode=2`. Require `bytes >= payload`. |
| `DEVICE_DESCRIPTOR_FAILURE` is a hidden mode | Registry comparison across three ports | **Excluded** — three different ports, same failure. It is a hung PBL caused by replugging mid-negotiation. |
| The logo window hides a fastboot | Custom SetupAPI watcher at 0.15 ms, 584 042 polls over 90 s | **Excluded** — for 15 s the device is *absent from USB in every form*. No `05C6`, no `17EF`, no `18D1`, no undocumented node. |
| EDL cable would reach real PBL | Physical EDL cable | Worked **once** — genuine `HELLO ver=3 mode=0` from PBL. Same `0x29` for the standalone ELF. Did not solve it. |

The last test is the one that closed the case. A genuine PBL-level EDL session is
the best access obtainable without a test point, and it fails identically.

State at end of phase: **software route exhausted.** Decision to send the tablet
to a repair centre.

Source: `session-notes/2026-11-08-morning.md`,
`session-notes/2026-11-08-evening.md`,
`session-notes/2026-11-08-night.md`.

---

## Phase 6 — submission

The tablet was submitted to a Lenovo-authorised service centre with:

- a two-page description of the fault,
- the diagnosis (bootloader partitions only; hardware healthy),
- both stock ABL payloads with SHA-256 sums,
- the exact partition offsets,
- an explicit note not to attempt what had already been ruled out.

See [`09-service-report.md`](09-service-report.md).

State at time of writing: **awaiting service.**

---

## Summary table

| Date | Milestone | Device state |
|---|---|---|
| Nov 3 | Unlock, Magisk root, kit extraction | Healthy, rooted |
| Nov 3 | Broken pivot flashed to `init_boot` | Hangs on logo |
| Nov 5 | ROCKNIX ABL flashed to both ABL slots | Soft bricked |
| Nov 6–7 | Gates 0, 1, 2 all fail at Firehose | Soft bricked |
| Nov 7 | Raw libusb transport rebuilt and proven | Soft bricked |
| Nov 8 | Battery, signing, substitution, timing, USB window — all excluded | Soft bricked |
| Nov 8 | Submitted to service | Soft bricked |
