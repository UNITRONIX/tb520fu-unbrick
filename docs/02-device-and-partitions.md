# Device and partitions

Hardware facts, the partition layout, and why `abl_a` / `abl_b` are the only
things that matter.

---

## 1. Identity

| Field | Value |
|---|---|
| Model | `TB520FU` |
| Codename | `lapis` (from `ro.product.device`, ABL `getvar product`, and the DT filename) |
| Marketing names | Lenovo Yoga Tab Plus, Lenovo YOGA Pad Pro 12.7 AI. Both names circulate for the same model number; do not treat them as different devices. |
| SoC | Qualcomm SM8650, Snapdragon 8 Gen 3, codename `pineapple` |
| GPU | Adreno 750 |
| RAM | LPDDR5X |
| Storage | UFS 4.0, multiple LUNs |
| Display | 12.7", dual-DSI, 2944×1840 |
| Touch / stylus | Novatek, Tianma or BOE panel variant |
| Keyboard | Pogo-pin folio, `lenovo_keyboard` driver |

**CORRECTION for readers of earlier community posts:** `TB520FU` is sometimes
listed as a MediaTek Helio G99 device. For this unit that is wrong — it is
Qualcomm SM8650 and speaks the Qualcomm Sahara/Firehose stack. Some Lenovo tablet
model numbers are close enough to confuse; verify with `getvar product` before
believing any guide.

---

## 2. Boot chain and where it broke

```
PBL (on-chip ROM, immutable)
 └─ XBL        flash: xbl / xbl_config        ← intact
     └─ TZ / Gunyah hypervisor               ← intact
         └─ ABL        flash: abl_a, abl_b   ← BOTH OVERWRITTEN
             └─ boot.img / init_boot.img     ← intact (never reached)
                 └─ Android                  ← intact
```

The failure is confined to one layer. Everything below it is proven working (the
device reaches EDL and speaks Sahara), and everything above it is untouched
(neither `boot` nor `init_boot` was modified during the final phase, and both
stock images are on disk).

This is why the repair is two writes and not a reflash of the whole device.

---

## 3. The two ABL partitions

Both are on **LUN 4**, each 1 MiB, 256 sectors of 4096 B.

| Partition | LUN | Start sector | Sectors | Byte offset | Size |
|---|---|---|---|---|---|
| `abl_a` | 4 | 95238 | 256 | 390 094 848 | 1 048 576 |
| `abl_b` | 4 | 437686 | 256 | 1 792 761 856 | 1 048 576 |

Offsets are derived from the stock `rawprogram4.xml` from ZUI 17.5.10.096 —
which is itself an encrypted `.x` in the newer packages, but this one yielded a
readable descriptor. Byte offset = `start_sector × 4096`.

Also confirmed in the same descriptor:

| Partition | LUN | Start sector | Notes |
|---|---|---|---|
| `devinfo` | 4 | 677222 | 1 sector; holds slot metadata and unlock state |

The `devinfo` partition is why reflashing ABL alone is sufficient and safe: the
unlock state and slot preference live elsewhere and were not damaged.

---

## 4. Payloads

Two stock ABLs, from two different firmware releases. Both verified against the
kit manifest.

| File | Size | Source package | SHA-256 |
|---|---|---|---|
| `stock_abl_a.img` | 1 048 576 | ZUI 17.5.10.096 | `4E13E55EC9BFE814404F5E7E71451263F9A3BF7A5B09F495DD40FE6D96822EB7` |
| `stock_abl_b.img` | 1 048 576 | ZUI 18.5.10.037 | `2E3D51734AD16F258AA9979BBA0B33AF2164E40040750C1FFF59D8184DB5DEB0` |

Only the first 241 464 B (`abl_a`) and 270 136 B (`abl_b`) are code; the rest is
padding to the 1 MiB partition size. The differing sizes are normal — the two
releases shipped different ABL builds.

Because the images are only meaningful up to their code length, flashing the whole
1 MiB (including padding) is the correct operation.

### Why two different firmware versions

`abl_a` came from the release the tablet was running when it was last healthy.
`abl_b` came from the newest available image at the time. Either would work; both
were prepared so the service centre has a choice.

---

## 5. Slots

| Field | Value |
|---|---|
| `current-slot` | `a` |
| `has-slot:abl` | yes |
| `slot-retry-count:a` | observed at 6 during the failure sequence |
| `slot-unbootable:a` | likely set once retries exhausted |

The A/B scheme exists so that a failed update can fall back to the other slot —
but only if the other slot is *good*. Flashing the wrong ABL to **both** slots
destroyed that safety net. This is the single most damaging decision in the whole
story, and it was made deliberately, with the risk written down in the manifest
one line above the command.

When ABL fails to boot, XBL decrements `slot-retry-count`. Once it reaches zero
the slot is marked unbootable and XBL stops trying, which is why after a while the
device settles into a stable crashdump loop instead of retrying forever.

---

## 6. What the device reports in fastboot

Captured before the brick, when fastboot still worked:

```
product: lapis
variant: SMP UFS
unlocked: yes
is-userspace: no
current-slot: a
has-slot:boot: yes
max-download-size: ~768 MiB
secure: yes
```

- `is-userspace: no` means this is real ABL, not `fastbootd`.
- `max-download-size` ~768 MiB is large enough for any custom boot image.
- `secure: yes` means AVB is present, but `unlocked: yes` means custom images are
  still permitted.

These values are worth recording because the same `getvar product` output is the
quickest way to confirm you are on the right model.

---

## 7. Related hardware notes

| Topic | Detail |
|---|---|
| USB | Single Type-C port, DWC3 controller `a600000.dwc3`, dual-role (host and device) confirmed via Android `dumpsys usb` |
| PMIC | Qualcomm, with GLINK to the Type-C controller on newer kernels |
| Fingerprint | Goodix, in TEE (`goodixfp64.mbn`). Do not confuse with the Goodix touch driver. |
| Panels | Two variants, Tianma and BOE — different DTB and different Novatek firmware. A mainline port must ship both. |
| Wi-Fi | WCN7850-class, `kiwi` firmware tree, ath12k on Linux |
| Audio | WCD codec + DSP topology in vendor XML |

More in [`08-linux-port-notes.md`](08-linux-port-notes.md).
