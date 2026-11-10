# The 900E → 9008 transition

On this tablet, EDL is rarely reachable directly. The device normally presents
`05C6:900E` — Qualcomm crashdump — and has to be *moved* to `05C6:9008`, the state
that speaks Sahara properly. This document is the full procedure, every variant
tried, and what the device actually answered.

This is the single most reused piece of knowledge in the repository: every later
session begins with it.

---

## 1. Why it is needed

| PID | What it is | Sahara `HELLO` mode |
|---|---|---|
| `05C6:9008` | genuine EDL, straight from PBL | `mode=0` (IMAGE_TX_PENDING) |
| `05C6:900E` | crashdump / diagnostics | `mode=2` (MEMORY_DEBUG) |

`mode=2` is not a programmer-loading mode. In it the device offers a RAM dump and
will happily acknowledge a **zero-byte** transfer as success — the false positive
described in [`03-sahara-protocol.md`](03-sahara-protocol.md) §7. To upload a
programmer you need `mode=0`, which in practice means you need `9008`.

The device reaches `900E` on its own, repeatedly:

```
Lenovo logo → USB absent (~15 s) → 05C6:900E → reset → repeat
```

It never reaches `9008` by itself. Something on the host has to ask for it.

---

## 2. The sequence that works

Measured, from a real session log (`catch2.log`, see §6 for the verbatim lines):

```
t+0.00   device present as 900E
t+0.57   HELLO ver=2 mode=2        ← crashdump, as expected
t+0.57   HELLO_RSP with mode=3     ← ask for COMMAND mode
t+0.57   device → cmd 0x0B         ← SAHARA_CMD_READY
t+0.57   SWITCH_MODE(0)            ← ask for IMAGE_TX_PENDING
t+0.57   device → cmd 0x01         ← HELLO_REQ again
t+0.57   HELLO_RSP with mode=0     ← confirm IMAGE_TX
t+0.57   device → cmd 0x04         ← END_TRANSFER, status 0
t+0.57   DONE_REQ                  ← close the exchange
t+21.36  device re-enumerates as 9008
```

Three things are worth noticing:

- **The switch is instant** (`0.57` → `0.57`). All five exchanges happen in the
  same millisecond tick of the log.
- **Re-enumeration is not instant.** It took **20.8 seconds** here. Scripts that
  give up after 2–3 seconds conclude "the bump failed" when it is still in progress.
- **The final `END_TRANSFER status=0` is expected**, not an error. It is how the
  empty image transfer completes. Without a following `DONE` the device stays in
  the Sahara state machine.

### Packet layout

Every Sahara packet is `uint32 cmd`, `uint32 length`, then payload.

**Step 1 — HELLO_RSP asking for COMMAND mode.** Twelve 32-bit fields, `mode=3`:

```
cmd = 0x02 (HELLO_RSP),  len = 0x30
payload: version, 1, 0, mode=3, 1, 2, 3, 4, 5, 6
```

**Step 2 — the switch itself.** `SAHARA_SWITCH_MODE = 0x0C`, 12 bytes total:

```
cmd = 0x0C,  len = 12
payload: mode = 0    (SAHARA_MODE_IMAGE_TX_PENDING)
```

The device answers with a fresh `HELLO_REQ` (`cmd=0x01`) instead of an ack. That
re-HELLO **is** the success signal.

**Step 3 — confirm.** `HELLO_RSP` again, this time `mode=0`.

**Step 4 — the empty transfer.** The device sends `END_TRANSFER` (`0x04`) with
`status=0`. Reply with `DONE_REQ` (`0x05`), 8 bytes.

### Minimal implementation

```python
pkt   = read_packet()                    # HELLO_REQ, mode=2
ver   = u32(pkt, 8)

write(hello_rsp(ver, mode=3))            # COMMAND
read_packet()                            # expect cmd 0x0B (CMD_READY)

write(pack("<III", 0x0C, 12, 0))         # SWITCH_MODE -> IMAGE_TX
r = read_packet()                        # expect cmd 0x01 (HELLO again)
if u32(r, 0) != 0x01:
    fail()

write(hello_rsp(u32(r, 8), mode=0))      # confirm IMAGE_TX
r = read_packet()                        # expect cmd 0x04 (END_TRANSFER)
if u32(r, 0) == 0x04:
    write(pack("<II", 0x05, 8))          # DONE

close(); wait for 9008 to appear          # allow 20-40 s
```

Full version: [`../scripts/sahara_bump.py`](../scripts/sahara_bump.py).

---

## 3. Variants, and which ones were needed

There is more than one way to ask, and the device does not accept all of them. This
is the part that is easy to get wrong, so the failed variants are documented too.

### V1 — empty END on 900E (`catch_usbclass`, the one that logged)

The sequence in §2. **This is the variant with hard log evidence**, and it produced
the 20.8 s re-enumeration.

```python
write(hello_rsp(ver, 3))                     # COMMAND
write(pack("<IIII", 0x0C, 12, 0, 0))         # SWITCH_MODE, 16 bytes on the wire
```

Log: `bump: COMMAND -> 11`, `bump: switch -> 1`, `bump: after ITX -> 4`.

Note the `11` is `0x0B` in decimal — `SAHARA_CMD_READY`.

### V1b — 12 bytes on the wire: also works (measured 2026-11-08)

`edlclient`'s `cmd_modeswitch` sends **12** bytes
(`pack("<III", 0x0C, 0xC, mode)`), and a session using it reached the same state:

```
[   0.089]   bump: HELLO ver=2 mode=2
[  20.807]   HELLO ver=3 mode=0  <- TRUE EDL from PBL
[  21.019]   END status=0x0 bytes=1554996/1569028
```

(`banner_capture.log`; same 20.7 s re-enumeration delay as V1.)

So the trailing zeroes in V1 are **not** what makes the switch work. The declared
`len=12` is what matters; the device consumes exactly that.

**What is measured and what is not:** 12 bytes has log evidence from two independent
sessions (`catch2.log`, `banner_capture.log`). The 16-byte form appears in
`oneshot_2026-11-08.py` but **no log confirms it reached 9008**. So "either is safe"
is not established — use 12 bytes, which is the form with evidence behind it.

### V2 — same, via `edlclient`

Identical semantics, using the library's `cmd_modeswitch`:

```python
hr(cdc, ver, sahara_mode_t.SAHARA_MODE_COMMAND)   # mode 3
sh.get_rsp()                                      # CMD_READY
sh.cmd_modeswitch(sahara_mode_t.SAHARA_MODE_IMAGE_TX_PENDING)
peek = sh.get_rsp()                               # HELLO_REQ
hr(cdc, ver, sahara_mode_t.SAHARA_MODE_IMAGE_TX_PENDING)
r2 = sh.get_rsp()                                 # END_TRANSFER
if r2["data"].image_tx_status == 0:
    sh.cmd_done()
```

This is the variant used by most of the later scripts because it reuses
`edlclient`'s framing instead of hand-rolling it.

### V3 — "already in IMAGE_TX", skip the switch

If `HELLO` arrives with `mode=0` — which happens after an interrupted session, not
after a normal boot — do not run the switch. Send an empty `END_TRANSFER` directly:

```python
write(pack("<II", 0x04, 16, 0, 0x0D))    # END_TRANSFER, status 0, image 0x0D
```

`image_id 0x0D` (13) is the programmer class; using it in the empty END keeps the
device's bookkeeping consistent. This path was coded as a fallback and is worth
keeping: it is the cheapest way out of a stale `mode=0`.

### V4 — Sahara EXECUTE instead of SWITCH_MODE

An attempt to reach other download modes through `SAHARA_EXECUTE` (`0x0D`) rather
than the switch command:

| Sub-command | Value | Result |
|---|---|---|
| `EXEC_CMD_NOP` | `0x00` | returns payload, no state change |
| `EXEC_CMD_SERIAL_NUM_READ` | `0x01` | returns the serial |
| `EXEC_CMD_MSM_HW_ID_READ` | `0x02` | returns HWID `0x2280e1` |
| `EXEC_CMD_SWITCH_TO_DMSS_DLOAD` | `0x04` | no useful effect |
| `EXEC_CMD_SWITCH_TO_STREAM_DLOAD` | `0x05` | no useful effect |

**None of these replace V1.** The exec path is useful for reading device identity
(and it is where HWID came from), not for reaching `9008`. Use `SWITCH_MODE`.

> **Correction, 2026-11-10 — this table does not reproduce on the current
> firmware.** Every one of these was retested against the real PBL (`9008`,
> `HELLO ver=3 mode=0`, command mode confirmed by `CMD_READY`), one command per
> freshly cycled session, with framing identical to `edlclient`'s `cmd_exec`
> (`<III`, len `0xC`):
>
> ```
> 0x02 MSM_HW_ID_READ         -> 0x1F EXEC_CMD_UNSUPPORTED
> 0x05 SWITCH_TO_STREAM_DLOAD -> 0x1F EXEC_CMD_UNSUPPORTED
> 0x08 GET_COMMAND_ID_LIST    -> 0x1F EXEC_CMD_UNSUPPORTED
> 0x09 GET_TRAINING_DATA      -> 0x1F EXEC_CMD_UNSUPPORTED
> ```
>
> `0x1F` means EXECUTE was parsed and the client command is simply not
> implemented — it is not a framing error. Note `0x02` is the control: it is the
> row this table credits with a concrete value (`0x2280e1`), and it now returns
> `0x1F`. So either that HWID came from a different firmware revision, or the
> value was carried over from an earlier tool run rather than produced in the
> session that recorded it.
>
> **Consequence:** "no useful effect" was too weak a statement for
> `SWITCH_TO_*_DLOAD`. They are **not implemented**, which closes the idea of a
> download path that avoids the Firehose programmer. Firehose is the only one
> this PBL offers.
>
> Also measured: a rejected EXECUTE leaves the device in the zombie `9008`
> state — enumerable but mute, cleared only by a manual power cycle. Sending
> several probes in one session yields one real result and several false
> silences.
>
> See [`15-crashdump-memory-access.md`](15-crashdump-memory-access.md) §6.

### V5 — physical: EDL cable

A cable that shorts the right pins can force a genuine PBL-level EDL, bypassing
crashdump entirely. It worked **once** on this device:

```
HELLO ver=3 mode=0          ← straight from PBL, no mode=2 stage
InstanceId: USB\VID_05C6&PID_9008\B&10BAF955&0&1   (a new USB port)
```

Subsequent attempts with the same cable produced nothing — the watcher saw only
`900E` and no transitions. Either the cable or the button timing is unreliable.

When it does work it is the best possible state: real EDL without any crashdump
residue. It does not fix the Firehose problem, but it removes a variable.

### V6 — physical: key combinations

Vol+ / Vol− / Vol+Power / Vol−Power at boot produced no readable input, because the
ROCKNIX ABL reads keys from AYANEO GPIOs. On a stock ABL these combinations are the
normal route to fastboot, not to EDL. Not a bump variant in practice, listed here
because it was tried as one.

### V7 — do nothing and wait

The device cycles `logo → 900E` on its own, roughly every 40–60 s. A catcher that
watches for `900E` and fires the bump at the right moment is more reliable than
trying to force anything. This is what the working scripts do: poll every 50 ms,
bump on the first `900E`.

---

## 4. Pitfalls, all of them observed

### 4.1 The 20-second wait

The switch completes in under a millisecond, but USB re-enumeration took **20.8 s**.
Allow **30–40 s** and poll. A 2-second timeout will make a working bump look like a
failure, and will then leave the device in an intermediate state for the next
attempt.

### 4.2 A pending `END_TRANSFER` blocks everything

If a previous session ended badly, the first packet read on `900E` is not `HELLO`
but `END_TRANSFER`. Sending `HELLO_RSP` to that does nothing useful.

Correct handling: send `SAHARA_RESET` (`0x07`), read the `RESET_RSP`, drain, then
re-read for `HELLO`. Two attempts with a reset between them resolve nearly every
stuck state.

```python
pkt = read_packet()
if pkt is None:                       # nothing pending
    write(pack("<II", 0x07, 8))
    drain()
    pkt = read_packet()
elif u32(pkt, 0) == 0x04:             # END pending
    write(pack("<II", 0x07, 8))
    drain()
    pkt = read_packet()
```

### 4.3 Never `RESET_STATE_MACHINE`

`0x13` kills the pipe and leaves the next attempt with nothing to talk to. `0x07`
(`SAHARA_RESET`) is the safe one. This mistake cost days; see
[`07-dead-ends.md`](07-dead-ends.md) §C1.

### 4.4 Do not `drain()` before reading `HELLO`

Draining discards the pending `HELLO`, and the device then waits forever for a
response. Drain only *after* a reset, never at the start of a fresh session.

### 4.5 Do not unplug the cable mid-negotiation

Replugging during the bump wedges PBL. The result is a node with
`HardwareID = USB\DEVICE_DESCRIPTOR_FAILURE` and `VID_0000&PID_0002` — see
[`07-dead-ends.md`](07-dead-ends.md) §D3. It is not a mode, it is a hang, and it
needs a power cycle (hold Power ~15 s).

### 4.6 The driver world matters

The bump needs the device bound to **WinUSB** if you use `pyusb`, or to a
**Qualcomm COM driver** if you use `QFIL`/`fh_loader`. They are mutually exclusive.
A bump performed in one world and then a flash attempted in the other will fail for
reasons that have nothing to do with the device.

Check which is bound:

```powershell
powershell -ExecutionPolicy Bypass -File <repo>/scripts/usb_watch/Kill-Orphans.ps1
```

### 4.7 Low battery breaks it in a confusing way

On a drained battery the bump may still succeed while the *upload* that follows
stalls at exactly 16 700 bytes. This looks like a bump problem and is not. Charge
first; see [`07-dead-ends.md`](07-dead-ends.md) §E1.

### 4.8 The device resets itself between sessions

After a failed session the device does not wait patiently on `900E` — it completes
its boot loop and cycles. Timing matters: fire the bump on the `900E` you just saw,
not on one you remember from five seconds ago.

---

## 5. Interpreting each response

| Response | Meaning | Action |
|---|---|---|
| `HELLO` `mode=2` | crashdump, normal starting point | proceed with the switch |
| `HELLO` `mode=0` | already EDL | skip to an empty `END` (V3) |
| `0x0B` `CMD_READY` | COMMAND mode accepted | send `SWITCH_MODE` |
| `0x01` `HELLO_REQ` after switch | **success**, device wants confirmation | send `HELLO_RSP mode=0` |
| `0x04` `END_TRANSFER status=0` | empty image closed | send `DONE_REQ` |
| `0x08` `RESET_RSP` | reset accepted | re-read for `HELLO` |
| `END status=0x0D` | device still in Sahara; a host frame was malformed | check lengths, retry after reset |
| silence after switch | the mode switch was refused | reset, re-read, try again |
| `9008` never appears | wait longer (up to 40 s), then power cycle | do not repeat blindly |

---

## 6. The verbatim log

From `catch2.log`, produced by `catch_usbclass_2026-11-08.py`:

```
[    0.00] === CATCHER (usb_class) ===
[    0.03] melf 1569028 B   state 9008=False 900E=True
[    0.03] waiting for device (10 min)...
[    0.06] 900E seen -> bump
[    0.57] bump: HELLO ver=2 mode=2
[    0.57] bump: COMMAND -> 11
[    0.57] bump: switch -> 1
[    0.57] bump: after ITX -> 4
[   21.36] bump: on 9008
[   21.37] ########## attempt 1 ##########
[   21.39] sahara conn: (1, 'sahara')
[   21.40] HELLO ver=3 mode=0
[   21.40]   READ[1] off=0 len=64 total=64
[   21.40]   READ[2] off=52 len=64 total=128
[   21.40]   READ[3] off=116 len=4096 total=4224
[   21.46]   READ[4] off=4212 len=652 total=4876
[   21.46]   READ[5] off=4864 len=64 total=4940
[   21.46]   READ[6] off=4916 len=384 total=5324
[   21.46]   READ[7] off=197376 len=11376 total=16700
[   21.48]   READ[8] off=8192 len=150544 total=167244
...
[   21.61] END status=0x0 loops=37 bytes=1554996/1569028
[   21.91] DONE=True
[   21.91] upload ok=True sent=1554996
[   21.91] probe[same] start
[   23.42]   [same] passive: silent
[   28.46]   [same] nop0 (+0.0s): silent
[   44.32] silent - close, wait, reopen
[   45.83] 9008 gone after DONE (programmer reset the device)
[   45.84] back on 900E -> crashdump, programmer did not stay
```

Two details in this log are worth pointing at:

**`READ[7] off=197376 len=11376`** — that offset is the hash segment of image `[1]`
(see [`04-melf-format.md`](04-melf-format.md) §5). The device reads it, which is why
`END status=0x0` is a real authentication success and not a formality.

**`HELLO ver=2` before, `HELLO ver=3` after.** The crashdump side speaks Sahara
version 2; the EDL side speaks version 3. If you see `ver=2` after a bump attempt,
the switch did not take.

---

## 7. Summary

| Question | Answer |
|---|---|
| Is a bump always needed? | Yes, unless an EDL cable gives a direct PBL session. |
| What is the command? | `HELLO_RSP(mode=3)` → `SWITCH_MODE(0)` → `HELLO_RSP(mode=0)` → `DONE`. |
| How long does it take? | Under 1 ms to switch, **~20 s** to re-enumerate. Wait 40. |
| What confirms success? | A fresh `HELLO_REQ` in reply to the switch, and later `HELLO ver=3 mode=0`. |
| What if `END` is pending? | `SAHARA_RESET` first, then re-read. |
| What must never be sent? | `RESET_STATE_MACHINE` (`0x13`). |
| Does `SAHARA_EXECUTE` work instead? | No — useful for reading HWID/serial, not for switching. |
| Does it solve the Firehose problem? | No. It only gets you to the starting line. |
