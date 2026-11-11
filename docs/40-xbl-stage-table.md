# The XBL boot chain, by name and address — and where FEDL sits in it

The devprg XBL core carries its own **stage table**: an array of
`{char *name, void (*fn)(void)}` pairs. It is the most useful artifact found so
far, because it converts a wall of code into a named boot sequence, and it shows
exactly where the forced-download path branches.

Reconstruct with `scripts/find_fedl.py`; the table lives at `0x148bfc88` in
image[2], 16-byte stride.

---

    10|## 1. The stage table, in order

```
[ 0] sbl1_hw_pre_ddr_init                     0x148302b0
[ 1] boot_fedl_check                          0x14843a7c
[ 2] boot_dload_handle_forced_dload_timeout   0x14863198
[ 3] sbl1_ddr_set_params                      0x1482e8a8
[ 4] sbl1_ddr_init                            0x1482d5f8
[ 5] store-logstomedia                        0x1483048c
[ 6] xbl_trng_ddi_seq                         0x1482d5f8
[ 7] store-logstomedia                        0x1482fd28
[ 8] xbl_map_smem                             0x14857f8c
[ 9] boot_smem_debug_init                     0x14857e98
[10] boot_smem_init                           0x14830694
[11] boot_ddr_share_data_to_aop                0x148306dc
[12] boot_populate_ddr_details_shared_table    0x1482e548
[13] boot_recovery_partitions_info_smem_init   0x1483078c
[14] boot_update_ram_partition_table           0x14826548
[15] sbl1_post_ddr_init                       0x14863440
[16] sbl1_hw_init_secondary                   (null)
[18] boot_post_ddr_dtb_load                    (null)
[20] aop_loaded                                (null)
[22] boot_dload_dump_security_regions          0x14830970
[23] EUD Init                                 0x14830978
[24] blacklist enable                          0x148309b8
[25] DP_Milestone                              (null)
[27] media_init:1                             0x14830a00
[28] boot_check_recoveryinfo_partition         0x1482ffa0
[29] boot_update_xbl_loaded_images_partition_id 0x1482e55c
[30] boot_recovery_select_boot_partitions      0x1482e550
[31] boot_recovery_partitions_info_imem_init   0x14830c74
[32] boot_save_sbl_recovery_partition_info     0x14844a2c
[33] boot_handle_trial_boot                    0x14830ddc
[34] boot_blacklist_disable                    (null)
[36] boot_update_abnormal_reset_status         0x14857e2c
[37] boot_cache_set_memory_barrier             0x14843850
[38] boot_smem_alloc_for_minidump              0x1482fdd0
[39] boot_shrm_mini_dump_init                  0x14830e1c
[40] boot_minidump_register_regions            0x14857e4c
[41] boot_smem_store_pon_status                0x14830eac
[42] boot_clock_init_rpm                       0x14830eec
[43] boot_vsense_copy_to_smem                  0x14826a08
[44] sbl1_tlmm_init                            0x148269c8
```

Two facts fall straight out of the ordering:

1. **`boot_fedl_check` (1) runs before `sbl1_ddr_init` (4).** The FEDL decision
   is made before DDR is initialised - which is why a device that fails in DDR
   init can still honour it.
2. **`boot_dload_handle_forced_dload_timeout` (2) sits between the check and DDR
   init.** So the timeout logic is a separate stage, not a wait inside the check.

## 2. Entry 3 is not `sbl1_ddr_init` — and that resolves an earlier conflict

`docs/16` §4.3 traced the "run DDR init" path to `0x1482e8a8`. The table shows
`0x1482e8a8` under the name **`sbl1_ddr_set_params`**, while `sbl1_ddr_init`
proper is `0x1482d5f8`.

That is consistent with `map_ddr_init.py`: the function at `0x1482e8a8` sets up
parameters, then calls `do_ddr_training`, and the work continues into
`0x1482d5f8`. `docs/16` was not wrong about the address — it was wrong to call it
the whole of DDR init. The stage table gives the correct split.

## 3. The forced-download timeout stage, decoded

`boot_dload_handle_forced_dload_timeout` (`0x14863198`) reads four properties by
numeric id:

```
0x21, 0x13, 0x1b, 0x0c
```

and then makes this decision:

```
0x14863268  bl 0x1484396c                 TCSR 0x1FD9000, bits 0x30
0x1486326c  ldrh w8, [x29, #0x1c]         the value of property 0x0c  (the timeout)
0x14863270  tst w0, #0xff
0x14863274  b.ne 0x148632c0               bits SET   -> take the "skip" arm
0x14863278  cmp w8, #0x10
0x1486327c  b.eq 0x148632c0               timeout==16 -> take the "skip" arm
0x14863280  ...                           otherwise: do the work
```

The work arm begins by logging **`Pre_DDR_clock_init, Start`** (`0x148b2441`),
takes the DDRSS clock tree up via `/dev/icbcfg/boot`, and then walks on into the
normal DDR path ending at **`sbl1_ddr_init, Delta`**.

### What that means

There are two ways to make the device take the short arm:

```
TCSR bits 0x30 set          -> skip
property 0x0c == 0x10 (16)  -> skip
```

`0x10 = 16` is a very specific value. `check_dp_timeout = 0x2710 = 10000` in the
DCB is a different number, so the two are not the same field: the DCB value is
almost certainly the **duration** and this is a **mode** (16 looks like
"disabled/no timeout" in a 0–16 enumeration).

So on this unit, with the DCB as it is, the arm taken depends on TCSR bits
`0x30` — the same bits `docs/16` §5 identified as the training guard. The two
decision points therefore share one condition, which is parsimonious: one latch
decides both.

> **Inference, labelled.** That the timeout stage and the training stage share
> the guard is read from identical calls to `0x1484396c`. It is not proven that
> they read it for the same purpose.

## 4. Why this matters for the goal

The goal is `HELLO ver=3 mode=0` from PBL. In this table, that state is produced
by stages 1 and 2 — both of which run **before** DDR init, and therefore before
the point where the programmer dies. That is the structural reason the hardware
route is worth pursuing: it does not have to pass through the broken stage.

It also explains why `docs/18`'s "50 ms poll" reading could not be the whole
story: the stage that decides is not a poll loop at all, and the wait is a
separate named stage with its own timeout property.

## 5. Still open

| question | evidence needed |
|---|---|
| the unit of `check_dp_timeout = 10000` | the consumer of property 0x0c; the string is read indirectly, so it needs a property-id map |
| what bits 1–5 of `0x221C8600` encode | SoC register documentation, or two boots with different shorts |
| whether the FEDL latch survives a full power cycle | one successful short, then read the register |
| whether `forced_download/feature = 1` alone (with a short) is sufficient | **physical test** — this is the next action |
