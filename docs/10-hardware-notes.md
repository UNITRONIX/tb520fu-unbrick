# Hardware notes: the ABL substitution

Why replacing the bootloader with an open-source one seemed like a good idea, how it
worked, and why it was the wrong move.

This document is the post-mortem of the decision that caused the brick.

---

## 1. The proposition

`ROCKNIX` publishes a signed `abl_signed-SM8650.elf` for SM8650 handhelds. Its
purpose is exactly what was needed: an ABL that can boot a Linux kernel instead of
handing off to Android.

If it worked, the tablet would have had a bootloader that loads a mainline kernel —
which would have made the Fedora port possible without fighting the stock ABL.

The manifest written before flashing contained, one line above the command, in
capitals:

```
WARNING=ROCKNIX ABL is for SM8650 handhelds (AYANEO Pocket S2 / KONKR), not
officially TB520FU/lapis.
```

Same silicon. Different board. The warning was accurate and was overridden.

---

## 2. What the binary is

| Property | Value |
|---|---|
| File | `abl_signed-SM8650.elf`, 258 048 B |
| `ph[0]` | `type=0`, off `0x000000`, 148 B — ELF header |
| `ph[1]` | `type=0`, off `0x001000`, 2 320 B — hash segment + certificates |
| `ph[2]` | `type=1`, off `0x002000`, 249 856 B — code |

### The code is not inspectable

- Entropy ≈ **7.03 bits/byte** — compressed or encrypted.
- Not gzip, xz, lz4 or zstd (magic bytes checked).
- Zero string hits for: `fastboot`, `ANDROID!`, `LINUX`, `extlinux`, `Volume`,
  `BootMode`, `devinfo`, `select`, `Android`, `Linux`.
- No low-entropy region anywhere (16 KB block scan).

So string-patching the binary to change its behaviour is impossible: there is
nothing legible to patch, and no unpacker.

### The signature is a test signature

```
qtestsign Root CA - NOT SECURE
qtestsign Attestation CA - NOT SECURE
validity: 20230101000000Z - 99991231235959Z
```

The private keys are public, in the qtestsign repository, in plaintext.

**This told us something genuinely useful:** XBL accepted this ABL, so XBL does not
enforce a Lenovo-only root of trust at that stage. Firmware secure boot is either
off, or the unlocked bootloader state relaxes it.

That fact was later over-applied — see [`06-signing.md`](06-signing.md).

---

## 3. Why the sources are not available

ROCKNIX's release workflow (`.github/workflows/release-abl.yaml`) builds from
`ROCKNIX/LinuxLoader`, which is a **private repository** (CI authenticates with
`secrets.LINUXLOADER_DEPLOY_KEY`). `git clone` returns
`remote: Repository not found`.

The README declares GPL-2.0. A GPL-2.0 project distributed as a binary with a
private source repository is a licence problem, and it is why no one outside
ROCKNIX can build a modified ABL from source.

Build dependencies listed in the workflow, for reference:
`build-essential crossbuild-essential-arm64 libc6-dev uuid-dev llvm clang lld`,
invoked as `./make_abl.sh all`.

---

## 4. Why the keys do not work on this tablet

The ROCKNIX ABL boots. It draws its loading screen. But:

- **Vol− and Vol+ are not read.** ROCKNIX documents menu = Vol−, Android = Vol+.
  Neither works here, even though the same ABL draws a battery indicator — so it
  *is* running and *is* reading *some* keys, just not these.
- **It does not hand off to Android.** The stock ABL finds the boot image via the
  slot metadata and the Gunyah boot path. The handheld build does not.

Probable cause: ROCKNIX ABL is built for AYANEO Pocket S2 / KONKR Pocket FIT. Those
boards have a different PMIC and different GPIO assignments for the volume keys.
The code reads keys — from the wrong pins. This also explains why the menu is
*unreachable* rather than *absent*.

Resulting loop:

```
Lenovo logo → crashdump (05C6:900E) → reset → repeat
```

---

## 5. Why this was circular

To change ABL behaviour you need to write to the ABL partition. Writing requires a
working EDL/Firehose session. The EDL session was the thing that was broken.

The plan implicitly assumed the capability it was trying to create.

And critically: **the substitution was never necessary for the repair.** The correct
stock ABL was already in hand, twice, verified, with offsets. The blocker was
always write access, not the ABL content. Building a better bootloader does not
produce write access — it is one layer above the broken one.

---

## 6. What the ABL analysis established

Despite the outcome, several useful facts came out of examining this binary:

| Fact | Significance |
|---|---|
| XBL accepts qtestsign-signed images | secure boot not enforcing a Lenovo root of trust at ABL stage |
| The ABL is compressed/encrypted | no string patching possible; only source builds could change behaviour |
| ROCKNIX sources are private | no community-modified builds are possible, regardless of the GPL claim |
| Key GPIOs are board-specific | a bootloader is not portable across boards even on identical silicon |

That last point is the one worth carrying forward. It is the mistake in one line.

---

## 7. The counterfactual worth recording

Had only **one** ABL slot been overwritten:

- XBL would have retried, found the good slot, and booted Android.
- `fastboot` would have been available.
- Two `fastboot flash abl_*` commands would have restored both slots.
- Total cost: ten minutes.

The A/B scheme exists exactly for this. Overwriting both was the decisive error, not
choosing the wrong ABL.

---

## 8. If you are considering a bootloader swap on a healthy device

| Check | Why |
|---|---|
| Does the ABL read this board's keys? | Test with the volume keys *before* flashing anything. If the menu does not appear on a ram-booted image, do not flash it. |
| Is the board DT compatible? | Same SoC is not enough. Display, PMIC, GPIOs and partition metadata all differ. |
| Are you overwriting one slot or both? | Never both. Not once. |
| Is `fastboot` still reachable? | If not, you have no way back. Confirm before, not after. |
| Do you have stock payloads with verified hashes? | Have them on disk, checksummed, before you start. |

And the rule that generalises beyond this device: **a bootloader is the one thing
you cannot debug from the host once it is wrong.** Every other partition can be
re-flashed after a mistake; the bootloader is what would do the flashing.
