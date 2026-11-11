# The remaining ROM images: searched, and there is nothing more in them

Before declaring the offline analysis finished, every image in the Lenovo package
that had not been examined was opened. This records what each contains, so the next
person does not repeat it.

---

## 1. What was checked

| image | size | content |
|---|---|---|
| `elabel.img` | 33 554 432 | **empty** - a volume with `/elabel`, `lost+found`, `test.txt` ("This file is used for test") |
| `lenovoraw.img` | 16 777 216 | **empty** - `/lenovoraw`, `lost+found` only |
| `lenovocust.img` | 314 572 800 | **encrypted** - one ASCII run in 314 MB |
| `metadata.img` | 2 261 268 | kernel build strings (`5.15.0-176-generic`), a `lenovo` tag |
| `metadata_3.img` | 10 539 008 | no ASCII at all |
| `persist.img` | 33 554 432 | normal Android persist tree; two licence serials, nothing boot-related |
| `logfs_ufs_8mb.bin` | 16 384 | a FAT12 volume header (`MSDOS5.0`, `BOOTMGR`) |
| `qweslicstore.bin` | 262 144 | no ASCII |

## 2. What that means

- **`elabel` and `lenovoraw` are placeholders.** Both hold a nearly empty filesystem
  with a test file. There is no board label, no pin map, no hardware description in
  either - which is where a board-specific configuration would most plausibly live.
- **`lenovocust` is encrypted** and therefore unreadable without the key. 314 MB of
  customer customisation that cannot be inspected.
- **`persist` holds no boot state.** It has the usual sensors/licences tree and two
  device licence serials, and nothing resembling slot metadata, PON history or a
  download cookie.
- **`metadata` is a kernel build artifact**, not a state store.

So the search for "somewhere in the ROM that describes the port or the boot request"
ends here: **no file in the package contains it.**

## 3. The complete inventory, now

Across this session every readable artefact has been examined:

| artefact | outcome |
|---|---|
| `xbl_s_devprg_ns.melf` | disassembled; stage table, gate chain, cookie read path decoded |
| `uefi.elf` | `uefiplatLA.cfg` extracted - `DloadCookieAddr = 0x1FD9000`, value `0x10` |
| `tz.mbn` | owns the cookie register in an ACL table; **no setter** |
| `XblRamdump.elf` | crash handler; `re-enter ramdump` is a retry loop, not a gate |
| `xbl_config.elf` | DCB + pre-DDR DTB - `forced_download` enabled, `skip_ddr_init_in_EDL = 0` |
| `DDRCS0_0_first40MB.bin` | memory map, two XBL boot logs, PON log, USB PHY snapshot table |
| `SHRM_MEM.BIN` | DDR firmware statics, no instantiated records |
| `sbl_pmic_dump.bin` | header + scattered log, 99.4 % zero |
| `stock_live.dtb` | USB PHY addresses, `gpio29` port-select, key wiring on three controllers |
| remaining ROM images | empty, encrypted, or unrelated (this document) |

## 4. The honest position

The goal is `HELLO ver=3 mode=0`. It has not been achieved, and it cannot be achieved
from the artefacts alone. Every path that could lead to it from data has been
followed to a conclusion:

```
cookie route      -> bit 12, no readable code sets it, TZ owns but does not set  closed
bump 900E->9008   -> needs a HELLO, and the node emits none                      closed
EUD               -> needs a debug policy no DTB declares                        likely closed
FEDL by short     -> condition is one latch bit; pin-out unknown                 OPEN
```

**One route is open, and it needs a wire rather than a file.**

## 5. What would change that

Three things, none of which can be produced by analysis:

1. **A verified Type-C pin-out for this model.** Then `docs/41`'s condition can be
   attempted: hold D+ low before power, and XBL's `boot_fedl_check` takes the branch.
2. **A genuine cold boot**, powered on once, no warm reset - the only thing that can
   return `dload_entry_count` to a first-entry state.
3. **A charged battery.** `VBAT 3588mV` and `UFS Gear 1 due to low battery` appear in
   both captured boots; that is a measured degradation, and removing it is free.

Any of the three is worth more than another pass over these files.
