# Analysis: replacing ABL with a "ROCKNIX without Linux" — is it feasible?

*Original: `ABL_SUBSTITUTION_ANALYSIS.md`. Translated faithfully.*

Date: 2026-11-08. The user's question: since the ROCKNIX ABL is open source, can a variant
be built that boots Android or fastboot directly, without Linux.

---

## 1. What we know about the ROCKNIX ABL (hard data)

### Origin

- Release workflow: `.github/workflows/release-abl.yaml` in `ROCKNIX/abl`
- **Source code: `ROCKNIX/LinuxLoader`** — a **PRIVATE** repository
  (CI uses `ssh-key: secrets.LINUXLOADER_DEPLOY_KEY`)
- `git clone` → `remote: Repository not found`
- Build: `./make_abl.sh all`, dependencies:
  `build-essential crossbuild-essential-arm64 libc6-dev uuid-dev llvm clang lld`
- Licence declared as **GPL-2.0** (in the README)

⚠️ **GPL-2.0 plus a private repository = a potential licence violation by ROCKNIX.**
So the sources are not available to us, even though in principle they should be.

### Structure of the binary `abl_signed-SM8650.elf` (258 048 B)

```
ph[0] type=0  off=0x000000  (148 B)     ELF header
ph[1] type=0  off=0x001000  (2320 B)    hash segment + certificates
ph[2] type=1  off=0x002000  (249856 B)  CODE - entirely opaque
```

### Code analysis (ph[2])

- **entropy ~7.03 bits/byte** → the code is **compressed or encrypted**
- not gzip, xz, lz4 or zstd (magic bytes checked)
- string search: **ZERO hits** for:
  ```
  fastboot, FASTBOOT, ANDROID!, LINUX, extlinux, EXTLINUX,
  Volume, volume, BootMode, devinfo, select, Android, Linux
  ```
- no region of low entropy (16 KB scan)

**Conclusion: the binary cannot be modified by patching strings.**
There is nothing to patch — the code is packed, and we have no unpacker.

### Certificates (ph[1], offset 0x12DC)

```
qtestsign Root CA - NOT SECURE
qtestsign Attestation CA - NOT SECURE
validity: 20230101000000Z - 99991231235959Z
```

**This is the key fact:** the ABL is signed with **qtestsign** test keys, which are
publicly available (`obbardc/qtestsign`, GPL-2.0).

Since the tablet's XBL accepted this ABL, it means **XBL accepts images signed with
qtestsign** — i.e. secure boot at the ABL level is disabled or bypassed (unlocked
bootloader).

## 2. Assessment of the idea: "ROCKNIX ABL without Linux boot"

### What it would give

If the ABL booted directly to Android or entered fastboot, we would have a writable
mode → `fastboot flash abl_a` → problem solved.

### Why it will not work in its current form

| step | feasibility |
|---|---|
| obtain the LinuxLoader sources | ❌ private repository |
| build our own ABL | ❌ no sources, no Qualcomm toolchain (sectools_v2) |
| modify the existing binary | ❌ code packed, zero strings, no unpacker |
| change behaviour via devinfo | ⚠️ requires **writing** to a partition — i.e. EDL, which we do not have |

**The key paradox:** to change ABL you need write mode. That same write mode is the goal
we are chasing. **The idea does not jump over the barrier — it assumes it is already
solved.**

### But there is something real in it

Replacing ABL **is not** needed for the repair. The **stock ABL** is enough (we have it).
The problem is not in ABL, but in the fact that we have no way to write it.

The ROCKNIX ABL is not the cause of the blockage — it is the **effect** of an earlier
operation. If we could write anything, we would write stock and be done. So building a
new ABL does not bring us closer to the goal by a single step.

## 3. What is still worth taking from this

### 3.1 qtestsign is public — and that is a gap

Since XBL accepts qtestsign-signed images, **any custom ABL could be signed** — if we had
the sources and the toolchain.

That opens a hypothetical route:

1. obtain sources compatible with LinuxLoader (e.g. old AOSP ABL / `edk2-porting`)
2. build a minimal ABL that **only enters fastboot**
3. sign it with `qtestsign.py aboot`
4. flash it → we have fastboot → flash the stock ABL

**But step 4 still requires write mode.** So it does not solve the problem.

### 3.2 The ABL menu does not respond — and we know why

From the ROCKNIX documentation: menu = **Vol−** at boot, Android = **Vol+**.
On our tablet **neither works**, even though the ABL draws the battery screen.

Probable cause: the ROCKNIX ABL is built for **AYANEO Pocket S2 / KONKR Pocket FIT**,
which have a different PMIC and different key GPIOs than Lenovo. The code reads keys, but
from the wrong pins.

**That explains why the menu is unreachable — not because it does not exist.**

### 3.3 What would realistically remain to be done if we had write access

If a write mode miraculously appeared, the order is simple:

```
fastboot flash abl_a stock_abl_a.img   (241 464 B, ABL from ZUI 17.5.10.096)
fastboot flash abl_b stock_abl_b.img   (270 136 B, ABL from ZUI 18.5.10.037)
fastboot reboot
```

Payloads ready, offsets confirmed, SHA256 matching the MANIFEST.

## 4. Conclusion

**The idea is technically correct, but unreachable and unnecessary.**

- unreachable: private sources, packed binary, no toolchain
- unnecessary: the stock ABL, which we already have, is sufficient

The real blockage is **lower** — the absence of write mode (firehose does not start,
fastboot does not come up). No ABL change bypasses that, because ABL is a layer **above**
the one that is broken.

## 5. What makes sense instead

1. **Charge the tablet fully** — test the DBC/battery hypothesis (the melf has
   `loader-dbc-threshold`, `skip-loader-dbc`, `vbatt-min`).
2. If that does not help — **test-point EDL** (a real 9008 from PBL, not via crashdump).
   Requires opening the case, but it is the only route to a real write mode.
3. Service — with a ready report of what is broken and what not to try.

---

> **Retrospective note:** §4's conclusion was correct and is the reason this document
> survived. The idea was technically sound and strategically useless, and the paradox in
> §2 is the whole story in one sentence: the repair required a capability that the
> attempted repair had destroyed.
