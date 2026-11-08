# Dead ends

Every approach that failed, with the reason. Read this before proposing an idea —
there is a good chance it is here, and the reason it failed is already known.

Grouped by category, roughly in the order they were tried.

---

## A. Off-the-shelf EDL tools

### A1. `bkerler/edl` — atomic mode

`edl printgpt --memory=ufs --lun=4` after a bump from `900E`.

Sahara reported `Loader successfully uploaded` (ver 3, HWID `0x2280e1`). Firehose
then raised `USBError` inside `configure`.

**Why:** the tool is correct; the programmer never starts. Nothing about the tool
choice changes that.

### A2. `QSaharaServer.exe` + `fh_loader.exe` (Lenovo's own tools)

These speak **COM ports only**. Every `oem*.inf` on the host mapped `05C6:9008`
and `900E` to WinUSB, so there was no COM port to open. After binding the Qualcomm
serial driver: Sahara completed (`rc=0`), then `fh_loader` reported
`Failed to open com port \\.\COM5` about 9 seconds later — by which time the
device had already left for the logo and returned as `900E`.

**Why:** same underlying wall, plus the driver-world confusion described in A6.

### A3. LTBox

Connected, EDL confirmed, loader accepted, Sahara complete. Then:

```
Firehose: configuring
Firehose read failed: os error 995      (I/O operation aborted)
EDL session open failed
```

**Why:** identical. Note that LTBox had been reported by others to work on
`TB520FU` — which is a useful data point: it works when the device is healthy. It
cannot rescue a device whose ABL is gone.

### A4. Native Linux host

Second machine, native Ubuntu, `edlclient`. Same programmers, two different
firmware revisions with different hashes:

```
Sahara upload OK (ver3, HWID 0x2280e1)
Firehose: USBError(19) immediately after DONE
```

**Why:** rules out the Windows USB stack and the entire WinUSB/`libwdi` situation
as the cause. This test was worth doing precisely because it removed a large
category of doubt.

### A5. USB 2.0 port instead of USB 3

No change. The USB version is not involved.

### A6. Mixing Qualcomm COM drivers with WinUSB tools

The two worlds are mutually exclusive:

| World | Driver | Tools |
|---|---|---|
| A | WinUSB (via Zadig or `libwdi`) | `edl.exe` (Temblast), raw `pyusb`, `qdl` |
| B | `qcser` / `qcusbser` (COM port) | QFIL, `fh_loader`, `QSaharaServer`, Lenovo `Rescue.cmd` |

Running `fh_loader` while the device is bound to WinUSB cannot work, and vice
versa — the tool cannot see the device at all. An unknown amount of early
debugging was spent switching tools without switching drivers.

**Lesson:** decide which world you are in, verify it with
`Get-PnpDevice -PresentOnly | ? InstanceId -match 'VID_05C6'`, and stay in it.

### A7. Temblast `edl.exe`

Downloaded and verified (handles MELF natively, `edl /l xbl_s_devprg_ns.melf`).
Never got as far as a different result — the failure is upstream of the tool.

---

## B. Signing and repackaging

### B1. Sign `prog_firehose_ddr.elf` with qtestsign

Three variants (v7/prog, v6/prog, v7/abl). All returned `0x29` after 64 bytes,
identical to unsigned.

**Why:** format rejection on the ELF header, before the hash segment is read. See
[`06-signing.md`](06-signing.md).

### B2. Substitute a signed Firehose inside the melf

Rebuilt the container with the signed image, all offsets preserved, size padded to
match exactly.

**Why:** `0x21` at byte 1 109 804 — before the substituted image at 1 117 008.
Whole-blob integrity check. No per-image digest exists in the file under any standard
algorithm tested, and one 652-byte metadata blob in the wrapper was never decoded, so
there was nothing to recompute even in principle.

### B3. Build a melf from scratch

Blocked: no description of the structure PBL validates, no hash table format, no
key. Mechanically possible to produce *a* melf; impossible to produce one the
device accepts.

### B4. Reuse a Motorola programmer with a matching HWID

A file in a loader collection had HWID `2280e1` — matching this device — but its
certificate chain was Motorola's (`Motorola PKI`, `Motorola Attestation CA 638-10`,
`Root CA 638`). Not Lenovo, not Qualcomm SRoT.

**Why:** wrong trust chain. HWID match is not identity.

### B5. Find a VIP digest table

The programmer contains VIP code (`VIP is enabled, receiving the signed table of
size %d`, `VIP hash table accepted`). Checked: no `Digest.elf`, no `Sign.bin`, no
magic `0x7CEF0312` anywhere in the ROM package, and nothing in a database of 2 745
loaders. For SM8650 only Xiaomi and OPPO digest tables exist publicly — no Lenovo.

**Why:** the artifact does not exist in our possession, and cannot be synthesised.

---

## C. Protocol-level

### C1. `RESET_STATE_MACHINE` (`0x13`) as a safe reset

Kills the pipe. Every subsequent attempt has nothing to talk to. Several scripts
used it as standard hygiene between retries.

**Fix:** `SAHARA_RESET` (`0x07`), which returns `RESET_RSP`.

### C2. Single-`read()` packet parsing

`read()` returns whatever is available, which may be several Sahara packets. Parsing
only the first header desynchronises the session and produces `0xD`.

**Fix:** buffer and consume exactly `length` bytes per packet.

### C3. `drain()` before reading `HELLO`

Discards the pending `HELLO` packet. The device then waits for a response that
never comes.

**Fix:** never drain before the first read of a session.

### C4. Sending `configure` before `DONE`

Hangs the WinUSB pipe: the log stops at `END 0x0`, `DONE` never arrives, and the
whole cycle is lost.

**Fix:** `END` → `DONE`, no peeking in between.

### C5. Trying `nop`/`configure` immediately after `END` without `DONE`

The device stays in the Sahara state machine and interprets XML as a Sahara packet,
answering `END_TRANSFER status=0x0D`.

**Fix:** `DONE` is mandatory; four variants confirmed it.

### C6. Trusting `END status=0x0` alone

In `mode=2` the device acknowledges a **zero-byte** transfer. A script checking
only the status reports success with nothing uploaded.

**Fix:** require `bytes >= payload size`. The reference scripts use
`MIN_SENT = 1_554_996`.

### C7. Long `sleep()` in the polling loop

Kills the resolution needed to catch fast transitions, and misses the ~8 s zombie
window entirely.

**Fix:** tight polling; the SetupAPI watcher achieves 0.15 ms.

---

## D. Physical access attempts

### D1. EDL cable

Worked **once**: a genuine `HELLO ver=3 mode=0` from PBL, without going through
crashdump. Best access obtainable without opening the case.

Outcome: `firehose_elf` → `0x29` after 64 B; `melf` → connection dropped;
`signed_melf` → no connection. Same wall.

Subsequent attempts with the same cable produced nothing — the watcher saw only
`05C6:900E` and no transitions. Either the cable or the key combination is
unreliable.

**Why it did not help:** a clean PBL-level session fixes the *starting state*, not
the programmer's runtime behaviour.

### D2. Key combinations for ABL menu / fastboot / recovery

Vol+, Vol−, Vol+ with Power, Vol− with Power — none read. The ROCKNIX ABL draws a
battery screen, so it is running, but its key GPIOs are mapped for AYANEO hardware.

**Why:** hardware mismatch, not a timing or technique issue.

### D3. `DEVICE_DESCRIPTOR_FAILURE` as a hidden mode

Hypothesis: the `VID_0000&PID_0002` node with no driver is an undocumented EDL
variant.

Refuted: three **different** ports each produced the same failure. A real mode
would appear on one specific port. `VID_0000` is a Windows placeholder, not a
vendor ID assigned by the device, and libusb cannot even see such a device.

**Cause:** replugging the cable mid-negotiation wedges PBL. Do not move the cable
while the device is in EDL.

---

## E. Hardware / power

### E1. Low battery as the root cause

Night session: transfers degrading from 1 554 996 B to 16 700 B over an hour, with
no code change. Looked exactly like a power problem.

9-hour mains charge → clean control run, full transfer, `END 0x0`. Degradation gone.

**Verdict:** real phenomenon, and the cause of the *instability*, but **not** the
cause of the missing Firehose — the clean run failed identically at the same point.

Note the trap: a low battery stalls the transfer at exactly the same 16 700-byte
offset as a missing ZLP does. Two unrelated causes, one symptom.

### E2. "Disable" the tablet to reset it

It cannot be powered off. Power always returns to logo, then crashdump. This is
fine — the catcher works in every cycle — but it means there is no clean cold
start.

### E3. Replacing ABL with an open-source one

See [`10-hardware-notes.md`](10-hardware-notes.md). Sources for `LinuxLoader` are
in a private repository despite a GPL-2.0 claim, the shipped binary is compressed
or encrypted (entropy ~7.03 bits/byte, no string hits, no recognised compression
magic), and any approach still requires write access — the very thing being
sought.

This is circular, and it is what bricked the device in the first place.

---

## F. Host hygiene problems

### F1. Orphaned processes holding the USB handle

Four `python.exe` processes from an earlier session held the device. `usb_class`
then returned `Permission denied`, which looks like a driver fault.

**Fix:** kill stale EDL processes before every session. Check
`Get-CimInstance Win32_Process -Filter "Name like '%python%'"` and compare start
times.

### F2. `edlclient`'s `usb_class` failing where raw libusb works

`usb_class(...).connect()` → `Permission denied accessing 05c6:9008`, while
`usb.core.find()` + `set_configuration(1)` + `claim_interface(0)` succeeds.

**Workaround:** use raw libusb for anything critical; do not conclude the device is
broken because a wrapper library cannot open it.

### F3. `pnputil /update-driver`

Does not exist on this Windows build; the elevated script silently dumped its usage
text. Driver forcing had to go through `UpdateDriverForPlugAndPlayDevices(FORCE)`.

### F4. Driver precedence

Lenovo's signed COM drivers (`oem59`, `oem37`, `oem63`) outranked the `libwdi`
WinUSB ones, so binding WinUSB required deleting the competing driver packages and
forcing the update on the live node, occasionally with a device removal and rescan.

---

## G. What was NOT tried, and why

| Not tried | Why |
|---|---|
| Disassembling the tablet / test point | Requires opening the case; warranty already at risk; the owner declined. |
| Reading `xbl`/`xbl_config` back for analysis | Needs write-capable EDL, which is the missing capability. |
| UART console | No accessible pads without disassembly. |
| Replacing the SoC or eMMC programming | Hardware-level; assumes the fault is storage, which the evidence contradicts. |
| Waiting for a leaked Lenovo SM8650 programmer | Possible, and the only zero-cost option, but open-ended. |
| Buying a second identical tablet to dump partitions | Would not help: the partition layout and payloads are already known and verified. Only the signing chain is unknown, and that is not on the storage. |

---

## Summary table

| # | Attempt | Outcome |
|---|---|---|
| A1 | `bkerler/edl` atomic | Firehose `USBError` |
| A2 | QSaharaServer + fh_loader | COM port unavailable after `DONE` |
| A3 | LTBox | `os error 995` at configure |
| A4 | Native Linux | `USBError(19)` after `DONE` |
| A5 | USB 2.0 | no change |
| A6 | Mixed driver worlds | tool cannot see device |
| A7 | Temblast `edl.exe` | never reached |
| B1 | qtestsign Firehose | `0x29` after 64 B |
| B2 | Signed image inside melf | `0x21` before substitution point |
| B3 | Build own melf | no structure, no key |
| B4 | Motorola programmer, matching HWID | wrong trust chain |
| B5 | VIP digest table | does not exist for Lenovo SM8650 |
| C1 | `0x13` reset | kills pipe |
| C2 | naive packet parsing | desync, `0xD` |
| C3 | `drain()` before HELLO | eats the packet |
| C4 | `configure` before `DONE` | hangs pipe |
| C5 | skip `DONE` | device stays in Sahara |
| C6 | trust bare `END 0x0` | zero-byte false success |
| C7 | long sleeps | kills resolution |
| D1 | EDL cable | worked once, same wall |
| D2 | key combinations | GPIO mismatch |
| D3 | descriptor failure as a mode | wedged PBL |
| E1 | low battery | real, but not the cause |
| E2 | power off | impossible |
| E3 | open-source ABL | circular, and caused the brick |
| F1 | orphaned processes | blocks USB handle |
| F2 | `usb_class` helper | fails, raw libusb works |
| F3 | `pnputil /update-driver` | not available |
| F4 | driver precedence | requires deletion and forcing |
