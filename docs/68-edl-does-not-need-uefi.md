# The boot that reached EDL never loaded APPSBL — so EDL does not need UEFI

`docs/67` concluded, correctly, that the stock UEFI is not resident on this tablet,
and then drew too strong a consequence: that the cookie route might be unavailable
because the code which stamps it is not the code that runs.

Comparing what the two logs actually contain corrects that.

---

    10|## 1. The comparison

```
log A (0x81A00000, Warm Reset)      APPSBL: no     boot_dload_entry: YES
log B (0x81CE4000, Shutdown)        APPSBL: yes    boot_dload_entry: no
```

**The boot that entered EDL did not load APPSBL at all.** It went from the RamDump
stage straight into the download path:

```
B -    847168 - TCSR reg value 0x10
D -         0 - ramdump_load_cancel
B -    847168 - RamDump -  Image Load, Start
D -      3050 - Auth Metadata
D -     15402 - RamDump -  Image Loaded, Delta - (890156 Bytes)
B -    862601 - boot_dload_entry          <-- EDL
B -    863607 - SBL1, End
```

No `APPSBL - Image Load, Start`. No UEFI. The download path was taken **before** the
stage that would have loaded the next bootloader.

## 2. What that means

**EDL is a terminal branch of XBL, not something reached through ABL or UEFI.**

That is consistent with the stage table (`docs/40`):

```
[22] boot_dload_dump_security_regions
[23] EUD Init
...
[27] media_init:1
[28] boot_check_recoveryinfo_partition
...
```

The dump/download stages sit at position 22 onward, while `APPSBL` loading is much
later in the sequence. A boot that takes the download branch never reaches the later
stages.

So the chain is:

```
XBL
 |-- if download requested --> boot_dload_entry --> EDL --> HELLO ver=3 mode=0
 |                              (never loads APPSBL)
 |
 +-- otherwise --> load APPSBL --> ROCKNIX ABL --> no handoff --> watchdog
```

**Two mutually exclusive outcomes from the same XBL**, and the one the goal wants is
the first.

## 3. This withdraws the pessimistic conclusion from `docs/67` §5

That section said:

> The download cookie is stamped by stock UEFI. Stock UEFI is not on the device. So
> the one route that produced `boot_dload_entry` in the captured log is a route this
> tablet can no longer take by itself.

**Withdrawn.** The reasoning assumed the request comes from UEFI. The working log
shows the opposite: on that boot, EDL was entered **without** UEFI ever loading. The
request came from somewhere that runs **inside XBL**, before APPSBL.

Where it came from is still open, but it is not "stock UEFI", because stock UEFI was
not involved in that boot at all.

## 4. So what requested the download on that boot?

Candidates, in the order the code suggests:

1. **The TCSR cookie was already set** before that boot - `TCSR reg value 0x10` is the
   value being read, not written. It could have been stamped by an *earlier* boot that
   did reach stock UEFI, before the brick.
2. **A download request from the previous crash**, recorded in SMEM or IMEM, which XBL
   consults (`boot_dload_dump_security_regions` is stage 22, immediately before).
3. **The `boot_dload_handle_forced_dload_timeout` stage** acting on a state left by
   the prior boot.

All three are consistent with the observation and none requires UEFI on *that* boot.

## 5. Why this raises the value of the offline work already done

The cookie address and value are documented (`docs/65`), the read path is located
(`docs/60` gate 2), and the counter is identified (`docs/59`). What is now clear is
that **the stamp can pre-exist a boot** - it is read from TCSR, which is a persistent
register in the always-on domain.

That means: if the stamp can be made present, **the very next XBL boot enters EDL
without needing anything else to work** - no UEFI, no ABL, no handoff. The ABL being
foreign is irrelevant to this path.

## 6. Status

Goal unchanged: `HELLO ver=3 mode=0` not obtained.

But `docs/67`'s gloom is corrected: the foreign ABL **does not block this route**.
The route is taken by XBL before APPSBL is loaded, and the captured log proves it was
taken on this device. The remaining unknown is narrower than before - not "the
firmware that stamps the cookie is missing", but "what set the stamp on that boot, and
how to make it set again".

That is a better question than the one `docs/67` left behind.
