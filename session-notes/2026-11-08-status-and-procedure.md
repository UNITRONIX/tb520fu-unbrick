# Status files and procedures

*Originals: `STATUS_PO_RESTARCIE.md`, `RANO_CZYTAJ_MNIE.md`, `STATUS_TERAZ.txt`,
`STATUS_TERAZ_LINUX_SYNC.txt` (see the separate file), `JUZ_NOTE_PL.txt`. Translated.*

These were working documents — written to be read the next morning by a person who had
slept, which is why they are so explicit. The tone is preserved.

---

## Part 1 — Status: where we are and what to do after restarting the tablet

*Original: `STATUS_PO_RESTARCIE.md`. Last updated 2026-11-08 ~00:40.*
Goal: restore stock `abl_a` + `abl_b` without opening the case.

### Tablet state

- Cycle: `Lenovo logo` → `crashdump 900E` → (bump) → `9008`
- It cannot be turned off — power always returns to the logo, then crashdump
- **This does not get in the way.** The catcher catches 900E in every cycle.
- Battery: charged overnight (DBC hypothesis still untested)

### What has been done (confirmed)

| element | status |
|---|---|
| Sahara → full melf transfer | ✅ `END 0x0`, `DONE True`, `high_water=1569028` |
| packet framing (strict) | ✅ fixed |
| ZLP (multiples of 512) | ✅ handled |
| `SAHARA_RESET` (0x07) | ✅ works, returns `RESET_RSP` |
| `RESET_STATE_MACHINE` (0x13) | ❌ **NEVER USE** — kills the pipe |
| `usb_class` (edlclient) | ✅ works after killing orphaned processes |
| raw libusb | ✅ works (`claim_interface` OK) |
| firehose after DONE | ❌ silence on all XML |
| logo window | ❌ device **absent from USB** (0.15 ms measurement) |

### NEW: SIGNED FIREHOSE (untested)

```
<KIT_DIR>\prog_firehose_ddr-signed-v7.mbn
  303 104 B, MBN v7, qtestsign, cert_chain 1632 B
  structure identical to the ROCKNIX ABL that XBL ACCEPTED
```

Hypothesis: Sahara was rejecting the unsigned firehose with `0x23`
(`HASH_TABLE_NOT_FOUND`). qtestsign adds a hash table → it should pass.

### Procedure after restart (in this order)

**Step 0 — check state**

```powershell
python -c "import usb.core; print('9008:',usb.core.find(idVendor=0x05C6,idProduct=0x9008) is not None,'900E:',usb.core.find(idVendor=0x05C6,idProduct=0x900E) is not None)"
```

**STEP 1 — kill orphaned processes (IMPORTANT)**
Without this, `usb_class` returns `Permission denied`.

```powershell
Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
  Where-Object { $_.CommandLine -notmatch 'mcp_idol|ms-python' } |
  Select-Object ProcessId, CommandLine
```

Kill the ones without a `CommandLine` (old EDL scripts) through UAC:

```powershell
Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$PWD\kill_orphans_elev.ps1" -Wait
```

**STEP 2 — test the signed firehose**
File: `firehose_signed_test_2026-11-08.py` (to be written — see below)

Sequence:

1. bump 900E → 9008 (proven trick)
2. `HELLO_RSP(IMAGE_TX)`
3. upload **`prog_firehose_ddr-signed-v7.mbn`** (303 104 B)
4. check `END status`:
   - `0x0` → **breakthrough**, go to STEP 3
   - `0x23` → hash table does not match → try `-v6`
   - `0x29` → PBL rejects the signature → path closed
   - `0xD` → transport problem
5. immediately `<configure MemoryName="ufs" ZlpAwareHost="1"/>` + `<nop/>`

**STEP 3 — write ABL (only if firehose responds)**

```python
# fh_loader or our own XML
write abl_a <- stock_abl_a.img   (LUN4, sector 95238,  256 sectors)
write abl_b <- stock_abl_b.img   (LUN4, sector 437686, 256 sectors)
```

Payloads:

```
<KIT_DIR>\abl_backup_stock\abl_a.img   4E13E55E...  (ZUI 17.5.10.096)
<KIT_DIR>\abl_backup_stock\abl_b.img   2E3D5173...  (ZUI 18.5.10.037)
```

**STEP 4 — verification**
Read back both partitions + compare SHA256. Then reboot and check fastboot/adb.

### Signature variants (if v7 does not pass)

```bash
cd <ROM_DIR>\qtestsign
SRC="...\image\prog_firehose_ddr.elf"

python qtestsign.py -v6 prog -o ...-v6.mbn "$SRC"
python qtestsign.py -v7 abl  -o ...-abl-v7.mbn "$SRC"
```

Additionally: cut image @0x110B50 out of the melf (that is firehose, entry 0x149997A8)
and sign it separately.

### Files that work (do not change)

```
<KIT_DIR>\
  catch_usbclass_2026-11-08.py     <- best catcher (usb_class)
  persistent_catcher_2026-11-08.py <- loop across cycles
  oneshot_2026-11-08.py            <- one run
  FastUsbWatch.exe                 <- 0.15 ms watcher (SetupAPI)
  kill_orphans_elev.ps1            <- kills old EDL processes
```

### What NOT to do

- ❌ `RESET_STATE_MACHINE` (0x13) — kills the connection
- ❌ `drain()` before reading HELLO — eats the pending packet
- ❌ `sleep` > 0.5 s in the wait loop — kills the resolution
- ❌ filter on `05C6` only — misses other modes
- ❌ trying to turn the tablet off — impossible, and unnecessary

### Most important finding

All layers on our side are **working**. The melf transfer completes in full, the device
confirms `DONE`. The problem: the programmer does not start as firehose. The qtestsign
signature is the **first untested hypothesis** for this blockage.

---

## Part 2 — Morning: what to do

*Original: `RANO_CZYTAJ_MNIE.md`. Created 2026-11-08 ~01:00.*
Tablet: **on the fast charger, left until morning.**

### ONE COMMAND FOR THE MORNING

```powershell
cd <KIT_DIR>
python rano_procedura.py
```

The script will:

1. take a **baseline measurement** (original melf) — if it does not give `END 0x0`, it
   stops and says "the tablet is still too weak"
2. if the baseline passes — test **signed v7**, then **v6**
3. if firehose responds — print a big message and we will write ABL

The result is saved in `rano_procedura.log`.

### State at the end of the night (2026-11-08 ~01:00)

**What is certain (with evidence)**

| finding | evidence |
|---|---|
| Sahara transport works | `END 0x0`, `high_water=1569028`, `DONE True` (at 00:15) |
| firehose does NOT start | silence on `<nop/>`, `<configure/>`, `MEMORY_DEBUG` |
| logo window = no USB | 0.15 ms measurement, 584 042 polls, 0 devices |
| qtestsign signature | **untested** — the transfer broke before the firehose image |
| the tablet was degrading | same file: 1 554 996 B → 16 700 B within an hour |

**What is a hypothesis**

**Battery / DBC.** The melf contains:

```
loader-dbc-threshold
skip-loader-dbc
vsys-min-recover-mv
vbatt-min
battery-low-threshold-mv
charger is not charging and device will shut down
```

The pattern "it worked, then stopped, with no code change" = deteriorating physical
conditions. The tablet lay in crashdump for weeks, powered from USB (500 mA).

### File state

**Ready to test**

```
xbl_s_devprg_ns_SIGNED_FH.melf        1 569 036 B   signed firehose v7
xbl_s_devprg_ns_SIGNED_FH_v6.melf     1 569 036 B   signed firehose v6
xbl_s_devprg_ns.melf (original)       1 569 028 B   control
```

**Payloads for writing ABL (once firehose comes up)**

```
stock_abl_a.img   1 048 576 B   sha=4E13E55E...   ABL from ZUI 17.5.10.096
stock_abl_b.img   1 048 576 B   sha=2E3D5173...   ABL from ZUI 18.5.10.037

abl_a: LUN 4, start_sector 95238,  256 sectors of 4096 B
abl_b: LUN 4, start_sector 437686, 256 sectors of 4096 B
```

**Scripts**

```
rano_procedura.py                <- MAIN, run in the morning
control_test_v3_2026-11-08.py    control test orig vs signed
test_signed_melf_2026-11-08.py   full signature test
melf_tool.py                     info / split / patch / verify
build_signed_melf_padded.py      builds melf variants
analyze_melf_map.py              melf structure map
FastUsbWatch.exe                 0.15 ms USB watcher
kill_orphans_elev.ps1            kills old EDL processes
```

### How to interpret the morning results

| result | meaning | next |
|---|---|---|
| baseline `end_0x0` + signed `end_0x0` + firehose ACK | **SUCCESS** | write ABL |
| baseline `end_0x0` + signed `end_0x0` + silence | signature accepted, programmer does not start | hardware hypothesis / test point |
| baseline `end_0x0` + signed `end_0x23` | hash table does not match | try other MBN variants |
| baseline `end_0x0` + signed `end_0x29` | PBL rejects the signature | signing path closed |
| baseline does not pass | the tablet is still weak | charge longer |

### What NOT to do

- ❌ Do not test the signature on a weak tablet — the results will be false
- ❌ Do not do `RESET_STATE_MACHINE` (0x13) — it kills the connection
- ❌ Do not use `drain()` before reading HELLO — it eats the pending packet
- ❌ Do not make many attempts in a row — every interrupted session leaves the device in a
  dead state and deepens the degradation

### Most important thing to remember

**Through the whole night we went from "we cannot send the programmer" to "we send it in
full and the device accepts it".** That is real progress.

One question is left: **does the programmer start after being accepted.**
If yes — we have fastboot and we write ABL in a minute.
If no — the cause is hardware, and we know that from measurements, not from guesses.

---

## Part 3 — Short status files

*Originals: `STATUS_TERAZ.txt`, `JUZ_NOTE_PL.txt`.*

### `STATUS_TERAZ.txt`

> ABL NOT written. Wedge: COM4 after SAFE_BUMP has HELLO 0B — **do NOT flash**.
>
> 1) Hard reset (Power ~10–15 s, cable). Goal: a fresh "QDLoader 9008 (COMx)" OK.
>    If it is 900E/QUSB_BULK again: Vol−+Power or Vol++Power (avoid dump).
> 2) Catcher PID in `CATCHER_PID.txt` — SAFE_BUMP=OFF; flash only on absent→COM +
>    HELLO>0.
> 3) No Zadig, no manual bump, no flashing the wedge.

### `JUZ_NOTE_PL.txt` (fragment)

> ABL NIE zapisany. Klin: COM4 po SAFE_BUMP ma HELLO 0B — NIE flashować.

Translation:

> ABL NOT written. Wedge: COM4 after SAFE_BUMP reports HELLO 0B — do NOT flash.

---

> **Retrospective note:** every prediction in the "how to interpret" tables turned out to
> apply — just not as hoped. The baseline passed (`end_0x0`), the signed variants returned
> `0x21` rather than any of the listed codes because the test used the melf-repacking route
> instead of the standalone MBN route, and the programmer stayed silent. The final line —
> "if no, the cause is hardware, and we know that from measurements" — is the accurate
> summary of how this ended.

