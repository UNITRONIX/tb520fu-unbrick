# Crash-dump memory access: what the 900E handler will actually give you

This document corrects a claim made earlier in this repository and records a
capability that was available the whole time and never used.

**The claim it corrects.** `docs/07-dead-ends.md` §G and `docs/05-firehose-and-the-silence.md`
state that DDR cannot be read in crashdump mode — "confirmed with small blocks".
That conclusion rested on a **single** probe at `0x9fa00000` returning `0xFF`.

**What is actually true.** In crashdump mode the device hands the host a table
describing every region it is willing to expose, by name. Reading that table is
a different operation from guessing an address, and it works reliably.

---

## 1. The memory table

`SAHARA_MODE_MEMORY_DEBUG` (`HELLO` with `mode=2`) is answered with
`SAHARA_64BIT_MEMORY_DEBUG` (`0x10`), carrying only two fields:

```
memory_table_addr    qword
memory_table_length  qword
```

Note: there is **no entry count** in the 64-bit form. A parser that expects
`<IQQ>` will misread everything. The 32-bit form (`0x09`) is
`<II>` and the entries use dwords.

Entry layout (64 bytes, confirmed against `edlclient`'s `parttbl_64bit` and by
the names coming out readable):

```
qword  save_pref
qword  mem_base
qword  length
char   desc[20]
char   filename[20]
```

On TB520FU that returns **53 entries / 3 392 bytes**. Reproduce:

```
python crash_region_probe.py
```

---

## 2. What the table contains

Grouped, with what each group is good for:

| Group | Example names | Useful for |
|---|---|---|
| Boot loader RAM | `OCIMEM.BIN`, `CODERAM.BIN`, `DATARAM.BIN` | running code, boot logs |
| Inter-processor mailboxes | `MSGRAM0..15.BIN` | subsystem state, `LIAM` tags |
| Shared memory | `SHRM_MEM.BIN`, `SMEMINFO.BIN`, `SMEM_VER.BIN` | **DDR training log**, boot info |
| PMIC / reset | `PMIC_PON.BIN`, `RST_STAT.BIN`, `PMON_HIS.BIN`, `FSM_STS.BIN`, `FSM_CTRL.BIN`, `DBG_EN.BIN`, `PMPONHIS.BIN` | why the device reset |
| Crash context | `CD_STRCT.BIN`, `CD_BTDDR.BIN`, `CD_BTIMM.BIN`, `CD_SHIMM.BIN` | crash structure and DDR snapshot |
| SBL PMIC dump | `sbl_pmic_dump.bin` (512 KiB) | SBL's own PMIC state |
| DDR windows | `DDRCS0_0` … `DDRCS2_3` | see §3 |
| IPA / DSP | `IPA_*.BIN`, `CPUCPFW.BIN`, `DCC_*.BIN` | irrelevant here |

Two entries had never been read successfully in earlier sessions and both read
fine with chunked 512 KiB transfers: `sbl_pmic_dump.bin` and `SHRM_MEM.BIN`.

---

## 3. How much DDR is exposed — measured

`ddr_near_probe.py`, single session, 4 KiB reads, 6 s timeout:

```
offset      address       verdict
0x0         0x80000000    real (code 92%, nz 35%)
0x1000      0x80001000    real
...
0x80000     0x80080000    real
0x100000    0x80100000    real (code 50%, nz 33%)
0x200000    0x80200000    real (code 54%, nz 24%)
0x400000    0x80400000    zeros
0x800000    0x80800000    zeros
0x1000000   0x81000000    zeros
0x2000000   0x82000000    0xFF
0x4000000   0x84000000    no-answer
```

So CS0 is readable for roughly the **first 2–4 MiB**, then returns zeros, then
`0xFF`, then stops answering. All the `DDRCS1_*` and `DDRCS2_*` windows return
`0xFF` at their bases.

**What this means and what it does not.** This is an *exposure extent* fact. It
is consistent with two very different situations and cannot separate them from
the host:

- the crash handler only mapped the low part of DDR, or
- DDR is genuinely only partly usable.

Do not read this as "DDR is broken". The earlier note did read the old evidence
that way, and that was the error.

The ABL load address `0x9fa00000` also does not answer, but it did not answer at
`0x80000000` either in that same second attempt — the session had degraded by
then, which is the more likely explanation than a per-address behaviour. Treat
any `no-answer` late in a session as suspect and re-test in a fresh one.

---

## 4. The DDR training log is reachable

This is the substantive find. `docs/05-firehose-and-the-silence.md` §8 lists the
DDR training result as one of the things that "would have told us the answer" but
was "unavailable", and §6.1 makes DDR bring-up one of the two surviving
explanations for the programmer's silence. Both assume the training outcome is
only observable over UART.

`SHRM_MEM.BIN` (256 KiB @ `0x24020000`) says otherwise. It contains the DDR
firmware's own data structures:

```
0x0938c  'DDR_FW version : 102.6.0'
0x093dd  'TRN_PRINT'          <- training print buffer label
0x093e7  'TRN_ISSUE'          <- training issue buffer label
0x09646  '%s: REASON=%s,FREQ=%s,CHANNEL=%s,CHIPSELECT=%s,BYTE=%s,BIT=%s,LIMIT=0x%X,VALUE=%d\n'
```

and the full stage list (all 11 present):

```
PLL Precal · DRAM DCC · RCW CDC/Full Cycle Sweep · DIT - Periodic Training
tWCK2DQI (DIT) · CLKIO DCC Monitor · RDT4 DCC Monitor · IO_Qual Vref Training
Low Freq DQ CDC perbit · HighSpeed DIT · PXI Config
```

plus a failure-reason table:

```
UNCATEGORIZED · INVALID_ECDT_ENTRY · LIMIT_EXCEEDED · NO_MEMORY_DEVICE_DETECTED
ONLY_RANK_1_OF_MEMORY_DEVICE_DETECTED · MEMORY_DEVICE_DOES_NOT_MATCH_OTHER_CHANNELS
READ_ZERO_EYE_OPENING · WRITE_ZERO_EYE_OPENING · RCW_TRAINING_FAIL · DIT_READ_FAIL
DCB_LOAD_FAIL · DCB_VERSION_INCORRECT · SDI_VERSION_INCORRECT
MANAGER_VERSION_INCORRECT · DRAM_DCC_FAIL · DCC_FAIL · LLCC_AS_TCM_FAIL
LLCC_LCP_CFG_FAIL · LE_RDQS_ALIGNMENT_FAIL · LE_PBIT_ALIGNMENT_FAIL
```

### What is proven and what is not

**Proven:** the training firmware's structures, its stage list and its failure
table are resident in shared memory and survive into the crash dump. Anyone who
needs DDR training state can read it from the host — no UART, no case opening.

**Not proven:** whether the last training run passed. The decisive test is
whether any *instantiated* failure record exists — a record would contain the
literal `REASON=` followed by values, whereas the format string has `%s` right
after it.

Measured (`decode_trn_buffers.py`):

```
buffers populated : lower half 95.1% nonzero, upper half 49.1% nonzero
'REASON=' found   : 1 occurrence, at 0x09646 — the FORMAT STRING
real records      : 0
```

Because the buffers are demonstrably populated, "no records" is meaningful
rather than vacuous: **no failure was reported by the DDR firmware in this
dump.** That weighs *against* hypothesis 6.1, but it does not close it — a hang
partway through training could occur before any record is written, and the
record layout was not decoded here.

> **Correction, 2026-11-10 late — this section overstated what was achieved.**
> A follow-up attempt to turn "the structures are present" into "here is how far
> training got" failed, and the failure is informative:
>
> 1. The stage table is regular. Each name is followed, 4-byte aligned, by a
>    unique 24-bit id in `0x00200000..0x002FFFFF`:
>
>    ```
>    PLL Precal 0x00217DE2 · DRAM DCC 0x002178AC · RCW CDC/Full Cycle Sweep 0x0021818A
>    DIT - Periodic Training 0x00218B90 · tWCK2DQI 0x00218B96 · CLKIO DCC 0x00217024
>    RDT4 DCC Monitor 0x0021744E · IO_Qual Vref Training 0x00212226
>    Low Freq DQ CDC perbit 0x00219ACE
>    ```
>
> 2. **None of those ids appears anywhere except its own definition slot** in the
>    256 KiB block. So the training *emission* log is not in `SHRM_MEM`.
> 3. Three u32 values sit right after the `TRN_ISSUE` label and look like buffer
>    addresses: `0x24070000`, `0x24072000`, `0x24075000`.
> 4. Reading those addresses returns nothing — while a control address in the same
>    session reads fine. Verified across separate sessions
>    (`session_kill_test.py`): control `0x24020000` → 4096 B every time;
>    `0x24070000` and `0x24072000` → 0 B every time.
>
> **Net result: the DDR training *outcome* is still not readable.** What is
> readable is the firmware's static data — versions, stage names, failure
> vocabulary. That is enough to know the structures exist and to name the stages,
> and not enough to say whether the last run passed.
>
> Consequence for hypothesis 6.1: the earlier "weighs against" must be withdrawn
> to **neutral**. The absence of failure records is consistent with success, but
> it is equally consistent with the records living in a buffer we cannot reach.
> Those two cannot be separated with what is available.
>
> One further check that is cheap and not yet done: `docs/05` describes the DDR
> image inside the melf as a *training* stage, while the ids above look like
> Qualcomm debug-message ids. Finding the id-definition format (the id space,
> the record header) would let the same ids be searched for in the
> `CD_BTDDR.BIN` crash-context snapshot, which IS readable.

That is the honest state of it. The next step for anyone continuing: decode
`TRN_PRINT` / `TRN_ISSUE` as ring-buffer records to recover the last events
rather than scanning for strings.

---

## 5. Reset cause, measured

Read from the same session, all four times observed identical:

```
RST_STAT   = 0x00000003     bits b0 and b1 set; b1 = WATCHDOG
PMIC_PON   = 0x02400200     low nibble 0 = PON_KPDPWR (power key)
FSM_STS    = 0x00021101
DBG_EN     = 0x00000874
```

Cross-referenced with timing from a passive watcher (`post_done_disconnect_2026-11-10.log`):

```
DONE acknowledged
+8.016 s   device leaves the USB bus
+23.584 s  back as 05C6:900E
```

The watchdog window measured elsewhere on this platform is **7.918 s ±3 ms**.
The observed 8.016 s is that same clock.

**Consequence for the DBC hypothesis.** `docs/05-firehose-and-the-silence.md`
§6.2 proposes that the programmer's battery guard powers the device down. A
power-down produces an absence **without** a watchdog reset. What is observed is
a watchdog reset. So the programmer does not appear to be shut down by its own
battery guard — it **starts, then hangs**, and the watchdog collects it.

This does not identify the hang, but it does rank the two remaining hypotheses:
6.2 loses support, 6.1 (hardware init) keeps what it had.

---

## 6. Sahara EXECUTE: closed on this unit

Worth recording because the two PIDs behave differently, one tells you nothing
about the other, and the repository contained a claim that does not reproduce.

On `900E` (`HELLO ver=2 mode=2`), command mode entered successfully:

```
0x00 NOP                   -> 0x1F EXEC_CMD_UNSUPPORTED
0x01,0x02,0x03,0x06..0x0A  -> 0x01 INVALID_CMD
```

On `9008` (`HELLO ver=3 mode=0`), command mode entered (`CMD_READY`), one command
per fresh session:

```
0x08 GET_COMMAND_ID_LIST    -> 0x1F EXEC_CMD_UNSUPPORTED
0x09 GET_TRAINING_DATA      -> 0x1F EXEC_CMD_UNSUPPORTED
0x05 SWITCH_TO_STREAM_DLOAD -> 0x1F EXEC_CMD_UNSUPPORTED
0x02 MSM_HW_ID_READ         -> 0x1F EXEC_CMD_UNSUPPORTED
```

The distinction between the two codes matters:

- `0x01 INVALID_CMD` — the packet was not understood at all (`900E`)
- `0x1F EXEC_CMD_UNSUPPORTED` — EXECUTE was parsed, and this client command is
  not implemented (`9008`)

**The `0x02` result is the control.** `docs/14-edl-mode-switch.md` §V4 records
`EXEC_CMD_MSM_HW_ID_READ` as returning HWID `0x2280e1`. On the firmware now on
this tablet it returns `0x1F`, on a freshly cycled session, using framing that
matches `edlclient`'s `cmd_exec` byte for byte (`<III`, len `0xC`). So either the
HWID reading came from a different firmware revision, or the value was retained
from an earlier tool run rather than produced in the session that recorded it.
Either way the claim is **not reproducible here**, and should not be relied on.

**Conclusion:** there is no Sahara download mode other than Firehose available on
this unit. `SWITCH_TO_STREAM_DLOAD` and `SWITCH_TO_DMSS_DLOAD` are not
implemented, so the idea of a programmer-free download path is closed — not
untested, closed.

Two protocol notes that cost real time:

- After `EXECUTE_RSP {cmd, len, client_cmd, data_len}` the payload is **raw
  bytes**, not a Sahara packet. Reading it as a packet desynchronises the
  session, and every later command then looks silent.
- A rejected EXECUTE (`0x1F`) leaves the device in the **zombie 9008** state:
  enumerable in PnP, permanently mute, only a manual power cycle clears it. Any
  script that sends nine probes in one session therefore reports eight false
  silences. Use one command per fresh cycle.

---

## 7. Practical notes

- A `9008` node can be present in PnP and completely mute (the zombie state,
  `docs/05-firehose-and-the-silence.md` §3). Always test responsiveness with a
  HELLO read before trusting it. Only a power cycle (hold Power ~15 s) clears it.
- Read large regions in 512 KiB chunks with generous timeouts. A single 256 KiB
  transfer timed out in `bootstage_probe.py` and returned nothing, which earlier
  looked like "region not available" and was not.
- Sessions degrade: reads late in a session can return `no-answer` for regions
  that answered cleanly at the start. Re-test suspicious negatives in a fresh
  session before recording them as findings.
