# EUD: what is established, what is not, and the one measurement that would settle it

A consolidation of the EUD line of inquiry (`docs\74`, `docs\75`), written because it
moved from "closed" to "first" in two steps and deserves a clear statement of where it
actually stands.

---

    10|## 1. Established

| fact | evidence |
|---|---|
| The EUD node exists and is enabled: `status = "okay"` | `stock_live.dtb` |
| Its second region is `0x088E2000`, named `eud_mode_mgr2` | same |
| `qcom,secure-eud-en` is present on the node | same |
| XBL reads bit 0 of `0x088E2000` to decide activity | `0x1488254c`, disassembly |
| That read happens **before** the D+ poll, in the same function | `0x14879650`, `docs\75` |
| EUD initialisation runs on a normal boot | both captured logs: `EUD Init`, `usb: qusb_dci_eud_init` |
| The boot DTB (pre-DDR) does **not** declare EUD | `xbl_config.elf`, 0 of 3 135 properties |
| No other image has an EUD string: `tz.mbn`, `devcfg.mbn`, `uefi.elf` all zero | searched |

So: the hardware is described as capable, the Android tree enables it, and the boot
code consults it before the route that needs a physical short.

## 2. Not established

- **Whether `usb_eud_is_active` returned true or false on any boot.** The function has
  a log string `"usb_eud_is_active, status %d"`, and **that line appears in neither
  captured log** - while `EUD Init` and `qusb_dci_eud_init` do. Either the function was
  not reached, or its logging is suppressed at this build's log level.
- **Whether secure EUD is permitted on this unit.** `qcom,secure-eud-en` marks the node
  as secure-mode; permission depends on fuse/secure state, which no file we hold
  describes.
- **What would make EUD active.** Nothing in the readable firmware sets the flag; the
  DT declares it, which is not the same as causing it.

## 3. Why the missing log line is worth noticing

Two of the three EUD-related messages print on every boot and one never does. That is a
shape, not a coincidence:

```
"EUD Init"                  printed, delta 0 us      (stage entry)
"usb: qusb_dci_eud_init"    printed                  (PHY init)
"usb_eud_is_active, status" never printed
```

The third is inside `usb_eud_is_active` itself (`0x14882570` references the string). If
the function were called on these boots, the line would appear unless logging is
filtered. So the most likely reading is: **the check is not reached on a boot that is
already taking the crash-dump path** - which is consistent with the ordering in
`docs\75`, where the check belongs to the *download-entry* function that this unit
never gets to.

That is an inference, and it is labelled as one.

## 4. The single measurement that would settle it

**Read bit 0 of `0x088E2000`.** It is a 16-bit read of an always-on register, and it is
the exact value `usb_eud_is_active` tests.

Two obstacles, both known:

1. `docs\45` §4 recorded that reading `0x088E2000` **kills a 900E session** - the same
   way `0xFD9000` does. So it cannot be read with the crash-dump handler alone.
2. Reading it at all needs a Sahara session, which is the standing blocker.

So the measurement is cheap in principle and blocked in practice by the same thing
everything else is blocked by.

## 5. What this means for the goal, stated plainly

The goal is `HELLO ver=3 mode=0`. EUD is now the most attractive route because it is
checked **before** the condition that needs a physical short, and because the DT says
the hardware supports it.

But it is **not** a route the host can take:

```
to reach EDL via EUD        need bit 0 of 0x088E2000 set
to set it                   need secure-EUD permission + some trigger
to learn if permission      need fuse state or a register read
to read the register        need a Sahara session
to get a session            need the goal
```

**The loop closes again.** That is the third time today: cookie (`docs\71`), bump
(`docs\34`), and now EUD.

## 6. The honest conclusion of the EUD inquiry

EUD is better understood than it was this morning, and it is genuinely more promising
than the ranking in `docs\42` suggested. But **every route inside the firmware requires
a precondition that only a working session or physical access can supply.**

Which leaves the position unchanged from `docs\73`:

```
FEDL by hardware short   - needs a wire and a pin-out
everything else          - needs something already broken to work
```

The EUD inquiry added understanding, not access. Recording that distinction is the
point of this document.
