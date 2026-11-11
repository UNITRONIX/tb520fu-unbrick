# What triggers the download cookie: the DBI dump library, not a key or a menu

`docs/65` established *what* the download cookie is (`0x1FD9000 = 0x10`) and that
UEFI writes it. This document answers the last offline question: **what makes UEFI
decide to write it.**

The answer is in the module that owns the write, and it is not a key combination or
a menu.

---

    10|## 1. The module

The string `ERROR: Failed to set DLOAD cookie` sits in a cluster that names its own
source file:

```
DloadCookieAddr
DloadCookieAddr not found in uefiplat.cfg
DloadCookieValue
DloadCookieValue not found in uefiplat.cfg
TzFastcall() failed for TZ_IO_ACCESS_WRITE_ID, Status = (0x%x)
EDLCookieAddr
DBI_Dump
   Could not find the DBI Dump region .
   DBI Dump region is invalid .
SkipDBISetup
NumCpus
Could not NumCpus uefiplat.cfg Defaulting to 8 cores
DbiDumpLib.c
   running_index == (22) || NumCores < (0x8)
SharedIMEMBaseAddr
Unable to get SharedIMEMBaseAddr from uefiplat!
DBI Dump table region assignment by TZ failed due to invalid argument or some other reason
ERROR: Failed to set DLOAD cookie
ERROR: Failed to get UefiInfoBlk!
```

**`DbiDumpLib.c`** - the DBI (data-bus-information / dump) library. So the cookie is
written as part of **dump infrastructure setup during UEFI boot**, not in response
to user input.

## 2. The code

The function that references those strings, at `0xa701dc60`–`0xa701dce8`:

```
0xa701dc60  add  x1, x29, #0x18
0xa701dc68  bl   0xa701d794             look up "DloadCookieAddr"
0xa701dc70  cbnz x0, 0xa701dcc8         not found -> log "CookieAddr not found"
0xa701dc78  cbz  w8, 0xa701dcc8         address zero -> same
0xa701dc7c  ldrh w9, [x29, #0x1c]       look up "DloadCookieValue"
0xa701dc80  movz w0, #0x502
0xa701dc84  movk w0, #0x200, lsl #16    w0 = 0x02000502
0xa701dc90  movz w3, #0x2
0xa701dc94  stp  x9, x8, [sp]           pass (value, address)
0xa701dc98  bl   0xa702e3a0             issue the write
0xa701dca0  cbz  x0, 0xa701dcd8         success -> return
0xa701dcac  add  x1, x1, #0x7b1         "...TZ_IO_ACCESS_WRITE_ID..."
0xa701dcb4  bl   0xa701add0             log the TzFastcall failure
0xa701dcd8  ret
```

So the sequence is:

```
1. read DloadCookieAddr  from uefiplatLA.cfg   -> 0x01FD9000
2. read DloadCookieValue from uefiplatLA.cfg   -> 0x10
3. call 0xa702e3a0 with (0x02000502, 2, address, value, 2)
4. on failure, log through the TZ_IO_ACCESS_WRITE_ID path
```

**The write goes through TrustZone.** That is why the neighbouring string mentions
`TzFastcall()`: the cookie register `0x1FD9000` is a secure TCSR, and the AP cannot
write it directly - it must ask the secure world. `0x02000502` looks like a
TZ service/command identifier.

## 3. So what triggers it

Nothing the user does. The path is:

```
UEFI boots
  -> DbiDumpLib initialises
  -> reads DloadCookieAddr / DloadCookieValue from its platform config
  -> writes the cookie through TZ
```

That means the cookie is set **by every successful UEFI boot that reaches this
library**, using the compiled-in values. It is not a "request" in the sense of a
command someone issues - it is a **stamp the firmware leaves behind**, saying "I got
here, and here is the dump mode I was configured for".

That explains the log lines exactly:

- the boot that reached EDL had `TCSR reg value 0x10` (`docs/58`) - the stamp was
  present;
- the boot that did not had no TCSR line - the stamp was absent.

And it means the difference between the two boots is **not** whether a dump was
requested, but whether UEFI got far enough to stamp the cookie.

## 4. Which reframes the counter

`docs/59` found `dload_entry_count`, compared against 2, gating `boot_dload_entry`.
Combined with the above:

| stage | what it does |
|---|---|
| UEFI boot reaches `DbiDumpLib` | stamps `[0x1FD9000] = 0x10` through TZ |
| next XBL boot reads the cookie | sees `0x10`, takes the download path |
| `dload_entry_count` increments | and at `>= 2` the "already entered" branch runs |

So **the stamp is what puts the device on the download path, and the counter is what
stops it repeating.** Two independent mechanisms, and both must be in the right state
for EDL.

## 5. The honest limits

- `0xa702e3a0` (the actual write) was **not decoded** - it is identified as the
  writer only by its position and arguments. `0x02000502` is presumed to be a TZ
  command id, not verified.
- The TZ side that receives it is in `tz.mbn`, which has not been examined.
- **Nothing here says how to make the device do this from the host.** The stamp is
  written by UEFI during boot; the host cannot invoke `DbiDumpLib`.
- Why the failing boot did not reach the library is still unknown - it may be earlier
  in the boot chain than this document reaches.

## 6. What this closes

The offline chain is now complete in the following sense: for every question of the
form "what decides X", there is either a decoded answer or a named place where the
answer is not readable. The one remaining physical unknown is unchanged - the device
must be made to **cold boot into a state where UEFI stamps the cookie and the counter
is still zero**, and that is a step no host-side tool can take.
