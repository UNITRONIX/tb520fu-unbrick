# Correction: the EUD node does exist — it is in the Android DTB, not the boot DTB

`docs/42` route C said "no `eud` property exists in either DTB" and concluded that EUD
could not be enabled because nothing declared it. That conclusion was drawn from the
wrong two device trees.

---

## 1. What was searched, and what was found

```
DTB                        properties   eud references
stock_live.dtb (Android)      23 900         14     <-- here
pre-DDR (xbl_config.elf)       3 135          0
DCB     (xbl_config.elf)       1 258          0
```

`docs/42` searched the two `xbl_config` trees - the ones the *boot chain* uses - and
found nothing. The node is in **`stock_live.dtb`**, the tree Android runs with, which
had not been checked for this term.

## 2. The node

```
/soc/qcom,msm-eud@88e0000
    compatible       = "qcom,msm-eud"
    reg              = 0x088E0000 (0x2000), 0x088E2000 (0x1000)
    reg-names        = "eud_base", "eud_mode_mgr2"
    interrupt-names  = "eud_irq"
    interrupts       = ...
    qcom,secure-eud-en          present
    qcom,eud-utmi-delay = 0x00FF
    status           = "okay"
    phandle          = 0x01C5
```

Two things matter:

**`0x088E2000` is the second region, named `eud_mode_mgr2`.** `docs/42` derived that
exact address from disassembly:

```
0x14882554  movz w8, #0x2000
0x14882558  movk w8, #0x88e, lsl #16     w8 = 0x088E2000
0x1488255c  ldrh w8, [x8]
0x14882560  tbnz x8, #0, ...             bit 0 -> EUD active
```

So the byte the firmware tests is inside a region the hardware description calls
**the EUD mode manager**. The static analysis and the device tree agree, and the name
confirms the interpretation: bit 0 of that block is a mode flag.

**`qcom,secure-eud-en` is present and `status = "okay"`.** The node is not disabled.

## 3. What this changes about route C

`docs/42` §5 ranked EUD last on the grounds that "no DTB property enables it, so it
likely needs the case opened". That reasoning was structurally wrong:

- the **boot chain** does not configure EUD - true, and now confirmed on the right
  trees;
- but the **Android DTB** declares it enabled, so the hardware is described as capable
  of it;
- and the flag that matters is `qcom,secure-eud-en`, which is about the *secure*
  side: `docs/66` showed this register block is written through
  `TZ_IO_ACCESS_WRITE_ID`, i.e. TrustZone owns it.

So EUD is not "undeclared". It is **declared, with a secure-mode flag**, in the tree
that Android uses. What is still unknown is whether that flag is honoured before
Android runs - the DTB that bootloader code reads is the pre-DDR one, which does not
mention EUD at all.

## 4. What this does not change

- **Nothing was tested.** EUD has still never been observed on this unit.
- The fact that the pre-DDR DTB has no EUD node means the *boot* path does not get
  this configuration from its own tree, and `docs/42`'s observation about the boot
  trees was correct as far as it went.
- `qcom,secure-eud-en` being present says the node is marked secure-mode; it does not
  say the mode is permitted on this unit's fuse state.

## 5. The corrected status of route C

| question | before | now |
|---|---|---|
| is EUD declared anywhere? | "no" | **yes, in `stock_live.dtb`, `status = okay`** |
| does the boot DTB configure it? | "no" | **no, confirmed on both boot trees** |
| is the register understood? | bit 0 of `0x088E2000` | same bit, now named `eud_mode_mgr2` |
| is it usable? | "probably needs the case" | **unknown - depends on secure-mode permission** |

Route C moves from "closed because undeclared" to **"open, with a named enabling
flag and an unknown permission"**. That is a better state than it was in, and it came
from searching a file that was already on disk.

## 6. Method note

Three times in this session a "does not exist" conclusion turned out to mean "was not
in the file I searched":

- `DDR_DATA` was "unreachable" until the log's encoding was fixed (`docs/33`);
- the dump order was "ascending by address" until the log was read properly (`docs/33`);
- EUD was "undeclared" until the Android DTB was searched (this document).

The pattern is consistent enough to be worth stating as a rule: **before concluding an
artefact does not exist, enumerate every file that could contain it and say which ones
were searched.** `docs/42` named two of the three DTBs available.
