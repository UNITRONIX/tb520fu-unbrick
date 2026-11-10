# Getting Firehose up: the actual mechanism

This document replaces hypothesis-driven guessing with the programming path as
the devprg itself describes it. It exists because the previous framing was wrong.

---

## 1. The contradiction that invalidates the earlier diagnosis

`docs/09-service-report.md` states the fault is confined to `abl_a` and `abl_b`,
and that "hardware and the lower boot stages are functional."

That cannot explain a Firehose hang, because **the EDL path never executes ABL**:

```
PBL (boot ROM)
  -> loads melf into RAM
  -> melf's own XBL core runs
  -> DDR bring-up
  -> Firehose programmer runs
  -> Firehose binds USB and speaks XML
```

`abl_a` / `abl_b` are partitions on UFS. Nothing above reads them. So whatever is
stopping Firehose is **not** the damaged ABL, and fixing ABL would not have
helped the EDL path even if writing were possible.

This is the most important correction in this document. The whole recovery plan
was built on a premise that the mechanism contradicts.

---

## 2. The real pipeline, from the devprg's own strings

Extracted from `xbl_s_devprg_ns.melf` in address order
(`scripts/ddr_pipeline.py`):

```
Entering DeviceProg DDR
sbl1_load_ddr_training_data      training data is LOADED from storage
boot_pre_ddr_dtb_load            a DTB is loaded from storage
sbl1_pmic_init
boot_cdt_init
sbl1_hw_platform_pre_ddr
sbl1_hw_pre_ddr_init
sbl1_ddr_set_params
sbl1_ddr_init
do_ddr_training
sbl1_wait_for_ddr_training       <- a blocking wait
sbl1_post_ddr_init
boot_post_ddr_dtb_load
boot_ddr_share_data_to_aop
boot_populate_ddr_details_shared_table
```

plus, separately:

```
DDR_INIT with shrm.elf           training is delegated to a module
boot_shrm_mini_dump_init
shrm_load_cancel
skip_ddr_init_in_EDL             a property that bypasses DDR init in EDL
sbl_error_handler FAIL: DDR not initialized
sbl_error_handler: Unable to get DDR initialization state
CDT not found in any storage media, using defaults
```

Three facts follow that matter operationally:

1. **Training is delegated.** The actual work is done by `shrm.elf`, which is
   image [4] of the melf (148 924 B at `0x15AB48`). The crash dump already showed
   the other side of it: `SHRM_MEM` contains `DDR_FW version : 102.6.0`, the
   `TRN_PRINT`/`TRN_ISSUE` buffers and all 11 stage names.
2. **Parameters come from files, not from the binary.** The module names
   `/A00C_8_0200_1_dcb.bin`, `/A00C_8_0100_1_dcb.bin`, `pre-ddr-lanai-1.0.dtb`
   and `/cpr.bin`. If a lookup fails it falls back and says so.
3. **A bypass exists.** `skip_ddr_init_in_EDL` is read as a property. There is
   code whose entire purpose is to not re-train DDR in EDL.

Fact 3 matters because of an observation already in hand: **the crash-dump handler
is running on DDR.** It reads memory through `SAHARA_MEMORY_READ` and returns real
data. So DDR is up. The programmer then re-initialises DDR from scratch anyway, and
that is the step after which it never speaks again.

Re-training working memory is not a neutral act. It is the single most plausible
place for a quiet hang followed by a watchdog.

---

## 3. The parameters are readable — this is new

`xbl_config.elf` contains a name table with (offset, length) pairs. The offsets are
**relative to the segment area at `0x200`**, not to the file — verified against the
ELF program headers, where `0xc918 + 0x200 = 0xcb18 = ph[3].off` and the lengths
match `ph[3].filesz` exactly:

| payload | offset | length | program header |
|---|---|---|---|
| `A00C_8_0200_1_dcb.bin` | `0xcb18` | `0x7018` | `ph[3]` |
| `pre-ddr-lanai-1.0.dtb` | `0x13b30` | `0x11e2c` | `ph[4]` |
| `cpr.bin` | `0x285bc` | `0xc804` | `ph[6]` |

Both the DCB and the pre-DDR DTB are **flattened device trees** (magic `d00dfeed`,
version 0x11), so their contents are readable rather than opaque:

```
dcb    28 696 B   140 nodes, 1258 properties
dtb    73 260 B   408 nodes, 3135 properties
```

Extract and decode with `scripts/extract_xbl_config.py` and `scripts/decode_fdt.py`.

### The DDR node, as declared

```
/soc/ddr:compatible          = "qcom,ddr"
/soc/ddr:ddr_boot_freq       = 0x1fef00      = 2 092 800 kHz ≈ 2093 MHz
/soc/ddr:ddr_log_level       = 0x0           logging off
/soc/ddr:ddr_trng_always_en  = 0x0
/soc/ddr:print_severity      = 0x2012
```

`ddr_log_level = 0` is worth noting on its own: whatever the DDR firmware would
say about failing, the board is configured **not** to print it.

---

## 4. What to actually do first

Ordered by information gained per unit of risk. None of these requires opening the
case.

### 4.1 Read the DCB values that the training consumes

`/soc/ddr` in both trees holds only seven properties:

```
compatible = "qcom,ddr"       ddr_boot_freq = 0x1fef00 (2 092 800 kHz ≈ 2093 MHz)
print_severity = 0x2012       ddr_log_level = 0
ddr_trng_always_en = 0        extnd_term_log_flag = 0        ddr_tr_led_flag = 0
```

**The memory part and the timing sets are not there.** A keyword sweep over all
1 258 + 3 135 properties finds no part number, no timing parameter, no per-frequency
table. Scanning the binary payloads for known SM8650 DDR frequencies finds nothing
in either DCB variant, but does find them in `cpr.bin`:

```
cpr.bin   200 000 kHz x2   768 000 kHz x3   3 200 000 kHz x1   0x1FEF00 x2
```

So the parameters that training consumes are **not** in the xbl_config payloads.
They live in the DCB file on UFS that the module names by path
(`/A00C_8_0200_1_dcb.bin`) — a different artefact from the same-named blob inside
`xbl_config.elf`. That is a concrete, checkable statement rather than a guess, and
it explains why the module treats `CDT not found` as a recoverable condition with
a fallback.

Consequence: comparing declared parameters against the silicon requires reading
that UFS file, which is exactly the access we lack. This line is bounded, not open.

### 4.2 Check the claim "CDT not found, using defaults" for this unit

The devprg has two messages: `CDT not found in any storage media` and
`CDT not found in any storage media, using defaults`. Whether this unit hits either
one changes which parameter path is used. The fallback path is exactly where a
board-specific mismatch would appear.

### 4.3 The bypass exists, is declared, and is already 0 — yet DDR init still runs

This is the section that changed after reading the code, so it is written carefully.

**The property is present in both trees, with value 0:**

```
/sw/boot:skip_ddr_init_in_EDL = 0
```

**The code that consumes it was located** (`find_prop_consumer.py`, one ADRP+ADD
reference, XBL core `image+0xd244`):

```
0x14831244  adrp x1, ...              property name
0x14831248  add  x0, sp, #0x8         node handle
0x1483124c  add  x1, x1, #0x619       "skip_ddr_init_in_EDL"
0x14831250  add  x2, sp, #0x4         &value
0x14831254  bl   0x1484ec14           get_property(node, name, &value)
0x14831258  cbnz w0, 0x148312c4       lookup failed
0x1483125c  ldr  w8, [sp, #0x4]       value
0x148312a4  ldr  w8, [sp, #0x4]
0x148312a8  cbz  w8, 0x148312d0       value == 0 -> path A
```

Path A (value 0, which is what this board declares) calls:

```
0x148312d0  mov x0, x19
0x148312d4  bl  0x14863198
0x148312dc  mov x0, x19
0x148312e0  bl  0x1482e8a8
```

**And `0x1482e8a8` is the DDR initialisation function.** It is a proper function
entry (stack frame setup at `0x1482e8a8`–`0x1482e8b8`), and directly after its
prologue it references the DDR stage strings:

```
0x1482e940  adrp x0, 0x148ab000 ; add x0, x0, #0xc1c   -> "sbl1_ddr_init"
0x1482eaf8                                              -> "do_ddr_training"
```

**So my earlier reading was wrong.** Zero does not mean "skip". Zero is the value
that *runs* DDR initialisation, and that is consistent with the observed behaviour:
the property is 0 on this unit, the initialisation function is called, and the
programmer never speaks again afterwards. A non-zero value would take the vtable
path at `0x148312ac` instead.

The lesson is worth stating because it is the third time in this project that a
name suggested one thing and the code did another: **a branch direction is evidence,
a property name is not.**

### 4.4 Stop re-plumbing the host

Four tool chains, two operating systems and a dozen protocol fixes all produced the
same result, because the failure is inside the device after `DONE`. Further host
work has a known outcome of zero.

---

## 5. What is still unknown, stated plainly

- Whether training actually completes or fails inside `0x1482e8a8`. The DDR
  training log is **not** reachable: `SHRM_MEM` holds the firmware's static tables
  but no emission records, and the buffer pointers next to `TRN_ISSUE`
  (`0x24070000`, `0x24072000`, `0x24075000`) are outside the dumped window and do
  not answer. See `15-crashdump-memory-access.md` §4.
- Whether the DCB parameters match this board's memory part. The part is identified
  numerically, and the parameters that training consumes live in a UFS file, not in
  the xbl_config payloads (§4.1).
- Whether the hang is even in DDR. `0x1482e8a8` is the DDR *initialisation* entry,
  which is consistent with the timing but is not proof — the call after it, and the
  code at `0x148312e8`, could equally be where it stops.

The difference from before is that these are now questions about **named functions
at known addresses**, not about an unknown black box. A next session can disassemble
`0x1482e8a8` directly and follow it stage by stage.

## 6. Honest position on the outcome

Nothing here makes the tablet flashable. The write capability is still missing, and
every host-side path to it has been measured as closed (`07-dead-ends.md`,
`14-edl-mode-switch.md`).

What has changed is that the failure is no longer a mystery at the mechanism level:

```
PBL accepts the programmer           measured, reproducible
XBL runs                             evidenced by the logo on screen
DDR initialisation is called         evidenced by the branch on a property
                                     that is 0 on this board
8.0 s of silence                     measured
watchdog reset at 7.918 s            measured, RST_STAT bit 1
```

That is a chain with one gap in it, not a wall with no door. The gap is inside
`0x1482e8a8`, and it can be read from a file on disk.

