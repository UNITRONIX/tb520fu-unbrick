# Firehose and the silence

This is the central finding of the whole effort. The programmer is accepted. Then
it never speaks.

---

## 1. The observation

One cycle, measured end to end:

```
t=+0.000   device on USB as 05C6:9008
t=+0.400   HELLO_REQ   ver=3  mode=0        ← genuine EDL, from PBL
t=+0.500   HELLO_RSP   ver=3
t=+1.000   READ_DATA × 37                   ← 1 554 996 B uploaded
t=+1.065   high_water reaches 1 569 028     ← whole file covered
t=+1.100   END_TRANSFER  status=0x0         ← programmer ACCEPTED
t=+1.150   DONE_REQ
t=+1.180   DONE_RSP      cmd=0x06           ← programmer CONFIRMED
t=+1.181   <configure> sent                 ← 1 ms later
t=+9.260   device GONE from USB
t=+24.000  device back as 05C6:900E         ← crashdump again
```

Between `DONE` and the disappearance: **total silence.** Not a rejection, not an
error, not a partial XML response. Nothing.

Repeatable across three consecutive boot cycles, to the second.

---

## 2. What was excluded, and how

The point of this section is not the conclusion — it is that each alternative was
killed with a measurement, not an opinion.

| Hypothesis | Why it was plausible | How it was tested | Result |
|---|---|---|---|
| Bad packet framing | `0xD` errors looked like transport faults | buffered framing, verified `high_water` | **excluded** — whole file covered |
| Missing bytes at the end | file is 1 569 028 but only 1 554 996 sent | compared `high_water` to file size | **excluded** — trailing 14 032 B is padding Sahara never asks for |
| Missing ZLP | stall always after a 512-aligned chunk | added ZLP for multiples of 512 | **excluded** — stall disappeared, behaviour unchanged |
| `configure` sent too late | maybe the window is sub-millisecond | sent 1 ms after `DONE` | **excluded** |
| Wrong command | maybe `nop` instead of `configure`, or a different XML | five variants, plus `getstorageinfo`, plus bare `configure` | **excluded** — silence on all |
| Wrong programmer | maybe the file was corrupt | original from the Lenovo package, SHA-256 verified | **excluded** |
| Wrong handle / zombie | reopening might help | reopened up to four times, plus same-handle | **excluded** |
| Wrong host or OS | Windows USB stack suspected | same result on native Ubuntu | **excluded** |
| Low battery | transfer had degraded during a night session | 9 h mains charge, then clean control run | **excluded as instability cause** |
| Signature | `0x23`/`0x21` looked like auth failures | signed variants tested | **excluded for this symptom** — original already passes |

Silence is not a response. Whatever is happening, it happens to the device's USB
side or below.

---

## 3. The zombie state

A detail worth recording because it misleads debugging:

After `DONE`, the `05C6:9008` PnP node **remains present for ~8 seconds** — but it
is unusable.

| Approach | Behaviour in that window |
|---|---|
| Open a new handle | hangs, times out |
| Write to the existing handle | accepted, no error, no effect |
| Read from the existing handle | timeout |
| `edl` in a subprocess | hangs or returns errno 19 |

The node is enumerable and present. It simply does not respond. Only after those
~8 seconds does it drop off the bus and re-appear as `900E`.

This produced a long series of false leads: scripts that saw `9008` present
concluded the programmer was alive, retried, and hung. The node being present is
**not** evidence that the programmer is running.

> **Rule taken from this:** treat "device present on USB" and "device responsive"
> as independent facts. Only a successful XML exchange proves Firehose is up.

---

## 4. What is *not* happening

It is worth being precise about the negative evidence, because it narrows the
search a lot.

- The device does **not** re-enumerate as an interface with `proto=0x11`. That
  profile is present only in the initial `9008` node, before the upload.
- There is **no** new VID/PID at any point: no `17EF` (Lenovo), no `18D1` (Google),
  no bare node without a driver.
- Fastboot never appears. Measured directly — see §5.
- The programmer does not re-request data. It does not retry. It does not
  complain.

So the programmer is not starting and failing to bind USB. As far as the host can
observe, the programmer simply never runs.

---

## 5. The logo window, measured at 0.15 ms

The most informative measurement in the whole investigation.

The hypothesis: during the Lenovo logo phase, there is a hidden mode — fastboot,
or a transient EDL — that fast polling would catch. Earlier scripts used
`sleep(1)` to `sleep(6)` and were dismissed as too coarse.

A native watcher was written against SetupAPI (`scripts/usb_watch/FastUsbWatch.cs`),
enumerating all USB device interfaces with no WMI, no libusb and no VID filter. It
polls in a tight loop with **no sleep at all**.

Result over 90 seconds:

```
[   0.001] baseline: 8 USB devices
[  42.517] - GONE    vid_05c6&pid_900e
[  57.501] + APPEAR  vid_05c6&pid_900e
[  90.005] === END: 584042 polls in 90.0s = 6489 polls/s (0.15 ms/poll) ===
new nodes: 1
```

**For 15.0 seconds (42.517 → 57.501) the tablet was absent from the USB bus in
every form.** No `05C6` with any PID, no `17EF`, no `18D1`, no undocumented node
with a missing driver.

At 0.15 ms resolution, 584 042 polls, nothing appeared. If a fastboot endpoint had
existed for even a fraction of that window, it would have been recorded.

**Conclusion (measured, not inferred):** during the logo phase there is nothing to
connect to. The device is either initialising hardware without raising USB, or it
has already moved past USB entirely. This is not a timing problem to be solved
with a better race — there is no race to win.

The earlier scripts were not wrong to be criticised for coarse polling, but the
criticism was beside the point: at high resolution the window turned out to be
empty.

---

## 6. The two remaining explanations

Both are on the device, and the host cannot distinguish them.

### 6.1 The programmer dies during hardware init

The melf contains explicit DDR bring-up:

```
Entering DeviceProg DDR
sbl1_ddr_init
do_ddr_training
```

It also carries image [4] — 148 924 B of DCB, pre-DDR device tree, PLL and DRAM
parameters. DDR training must succeed before the programmer can touch UFS, and if
it fails the programmer typically hangs or resets without ever raising USB.

This is consistent with everything observed: accepted image, no endpoint, device
gone ~8 s later.

### 6.2 The programmer is shut down by its own battery guard

The melf contains Dynamic Battery Check parameters and messages:

```
loader-dbc-threshold
skip-loader-dbc
vsys-min-recover-mv
vbatt-min
battery-low-threshold-mv
no-battery-charger-threshold-mw
low-battery-charger-threshold-mw
charger is not charging and device will shut down
battery recover failed
Loader dbc skipped. VBAT: %dmV
```

If `VBAT` is below the threshold, the programmer **powers the device down instead
of initialising storage**. That produces exactly the observed shape: transfer
fine, `DONE` fine, then a quiet death rather than a Firehose endpoint.

**But:** a 9-hour charge produced a clean control cycle with a full transfer and
`END 0x0`, and the outcome was still silence. So low voltage explains the
*instability* observed late at night (when transfers died at 16 700 B), not the
absence of Firehose.

The remaining possibility is that the battery is *healthy* but the DBC still
trips — for instance on a failed charger detection, or because the fuel gauge
reports a state the programmer does not accept. That cannot be distinguished from
the host.

> **Update, 2026-11-10 — this hypothesis loses support.** A power-down and a
> watchdog reset are distinguishable in the crash dump, and it is a watchdog:
>
> ```
> RST_STAT = 0x00000003      bit 1 = WATCHDOG, four separate observations, identical
> DONE -> device leaves USB  +8.016 s
> platform watchdog window   7.918 s +/- 3 ms   (measured elsewhere on this SoC)
> ```
>
> The 8.016 s is that same clock. A DBC shutdown would leave the device off the
> bus **without** a watchdog reset. So the programmer is not being shut down by
> its battery guard — it starts, hangs, and is collected by the watchdog.
>
> That does not identify the hang. It does mean 6.2 should not be carried forward
> as a live alternative to 6.1. Details:
> [`15-crashdump-memory-access.md`](15-crashdump-memory-access.md) §5.

### 6.3 Which is it?

Unknown, and it does not change the remedy. Both end at the same place: a service
or test-point intervention. The distinction would only matter if a fix existed on
the host side, and no host-side action changes either one.

---

## 7. Why the test-point route is different

A test point forces the SoC into EDL **before** XBL ever runs, from a clean PBL
state. That is a meaningfully different starting condition:

| Normal path (what failed here) | Test-point path |
|---|---|
| XBL runs, crashdump or partial EDL | PBL only, no XBL |
| Programmer accepted, never starts | Clean PBL state, no crashdump residue |
| `mode=2` or degraded `mode=0` | `mode=0` from a clean state |
| Device may be wedged from prior sessions | Wedge impossible — state is forced |

It does not bypass signing (the programmer is still checked), but it removes every
variable that the host cannot control. This is why it is the recommended next step
and why it requires opening the case.

---

## 8. What would have told us the answer

Things that were unavailable and would each have resolved the ambiguity:

- **UART.** A serial console from XBL/programmer would show DDR training progress
  and any DBC message directly.
- **`Loader dbc skipped. VBAT: %dmV` from the device.** The string format means the
  value is printable; it just goes somewhere we cannot see.
- **pstore / ramoops after a failed boot.** Attempted during the Linux bring-up
  (`pstore_dumps_*` in the original kit), but with the bootloader broken there is
  no kernel to write a log.

The pattern is that all three require the device to reach a state that the broken
bootloader prevents. This is the practical definition of the dead end.

> **Correction, 2026-11-10 — the first item on that list is wrong for DDR.**
> The DDR training result does not require UART. `SHRM_MEM.BIN`, which the
> crash dump exposes, contains the DDR firmware's own log structures:
>
> ```
> 'DDR_FW version : 102.6.0'
> 'TRN_PRINT'  'TRN_ISSUE'
> '%s: REASON=%s,FREQ=%s,CHANNEL=%s,CHIPSELECT=%s,BYTE=%s,BIT=%s,LIMIT=0x%X,VALUE=%d'
> all 11 training stage names, plus a 20-entry failure-reason table
> ```
>
> Measured on this unit: the buffers are populated (95% / 49% nonzero) and contain
> **zero instantiated failure records** — only the format string. That weighs
> against hypothesis 6.1 rather than confirming it, though it does not close it
> (a hang can occur before any record is written).
>
> So the DDR half of 6.1 is now answerable from the host, and should be answered
> before anyone pays for a board swap or a test point.
> See [`15-crashdump-memory-access.md`](15-crashdump-memory-access.md) §4.

---

## 9. Summary

| Question | Answer |
|---|---|
| Is the transport good? | Yes — full payload, `END 0x0`, `DONE` acknowledged, repeatably. |
| Does Firehose ever answer? | Never. Not `nop`, not `configure`, not `getstorageinfo`, in any session. |
| Is the device present but silent? | For ~8 s after `DONE`, yes — present in PnP, unusable. |
| Is there a hidden mode after `DONE`? | No. 0.15 ms polling over the entire window found nothing on the bus. |
| Is it the cable, drivers, host or tool? | No. Four tools, two operating systems, identical result. |
| Is it the signature? | Not for this symptom; the original signed programmer already passes. |
| What is left? | Hardware-side init failure or DBC shutdown. Both need service. |
