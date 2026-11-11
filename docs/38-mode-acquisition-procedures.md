# Mode acquisition: the procedures, frozen

This is the document to read when you need a mode, not an explanation. Every
procedure below is either measured on this unit or marked as unverified.

**Rule for this file: it does not change.** If a procedure stops working, check
the preconditions first. Every failure analysed on 2026-11-11 came from a
precondition being violated, never from the device changing.

---

    10|## The tool

```
python scripts/tablet.py <command>
```

| command | what it does | writes to the device |
|---|---|---|
| `status` | what is on the bus, which COM port | nothing |
| `selftest` | verifies the whole chain, changes nothing | nothing |
| `wait --want 900e` | polls until the mode appears | nothing |
| `read --region DDR_DATA` | HELLO → MEMORY_DEBUG → read a region | HELLO_RSP only |
| `bump` | 900E → 9008, then grabs the 9008 HELLO | mode-switch commands |
| `catch` | holds a handle across a power cycle, reads the HELLO, switches **on that handle**, grabs the 9008 HELLO | mode-switch commands |
| `edl-hello` | reads the HELLO off a 9008 node already present | nothing |

**CORRECTION (docs/100).** This file used to describe `bump` and `wait --want 9008`
as two steps. That could never work: the HELLO is consumed by the first opener, so a
second process finds silence. Both callers now do the switch on the handle that holds
the HELLO, and `catch` covers the whole of route (a) in one command.

Everything else in `scripts/` that talked to this tablet has been moved to
`scripts/_superseded/` and must not be used. Eight overlapping catchers existed
by the end of 2026-11-11; the timing model kept changing between them, which is
why a procedure that worked stopped working. That is the failure this file and
that one script exist to prevent.

---

## 1. 900E — crashdump, the resting state

**This is the state the tablet reaches by itself.** If it is in no mode, it is
here or off the bus.

```
python scripts/tablet.py status
```

Expected:

```
PID_900E  USB\VID_05C6&PID_900E\<serial>
COM port: COM<N>
```

Driver: `qcwdfserial`, registered as "Qualcomm HS-USB Diagnostics 900E".

### Preconditions

- the Qualcomm serial driver owns the node, not WinUSB. `status` shows a COM
  port when this is true; when it shows no port, the node is on WinUSB and
  `tablet.py` cannot reach it.
- the node is not a **ghost**: after a power cycle a stale node can appear for
  ~14 ms and then vanish. Opening it yields `OSError 995`. Wait for the node to
  be continuously present before opening — `read` handles this internally.

---

## 2. The HELLO, and why almost everything fails here

**Sahara emits exactly one HELLO per boot, and the first reader takes it.**

Measured facts, all on 2026-11-11:

| observation | evidence |
|---|---|
| the HELLO waits for the first opener | the vendor tool opened the port ~18 s after boot and its first read returned a complete packet |
| after it is taken, silence until the next real boot | hours of attempts, all silent |
| `SAHARA_RESET` (`0x07`) does not produce another | tested twice, and independently with the vendor tool |
| `SAHARA_RESET` at the end of a session **destroys the port** | six sessions, port gone 16 ms later, every time |
| a bare open with zero writes keeps the port alive | 45 s control, no disappearance |
| a cold key-hold reset does not always restore it | one full cycle with a held handle, zero bytes |

**Consequence:** there is no client-side trick that recovers a spent HELLO.
Before any command that needs it (`read`, `bump`), check `selftest`. If
`bytes pending` says `none (HELLO spent)`, that operation cannot succeed until
the board has really power-cycled.

---

## 3. 9008 — real EDL (Sahara ver=3, mode=0)

**Verified to work, twice, from a fresh 900E.**

```
python scripts/tablet.py catch --seconds 180
```

One command: it holds a handle across the power cycle, reads the mode=2 HELLO, runs the
switch **on that same handle**, then races for the 9008 HELLO and reports whether it is
`ver=3 mode=0`. This replaces the old `bump` + `wait` pair, which could not work - see
`100-the-two-process-bump-could-never-work.md`.

The bump sequence, and what each reply means:

```
HELLO ver=2 mode=2          -> send HELLO_RSP(mode=3)
CMD_READY (0x0B)            -> accepted; send SWITCH_MODE(0), 12 bytes
HELLO_REQ (0x01) again      -> success signal, not an error; confirm with HELLO_RSP(mode=0)
END_TRANSFER status=0       -> expected; send DONE_REQ
<20 s of silence>           -> the device re-enumerates as 9008
```

### Preconditions

1. **a fresh HELLO** (see §2). This is the one that fails.
2. allow **40 s** for re-enumeration. It measured 20.8 s once. A 2 s timeout
   makes a working bump look broken and leaves the device mid-state.
3. never send `SAHARA_RESET_STATE_MACHINE` (`0x13`). It kills the pipe.

### Status: currently NOT reproducible on this unit

The sequence is documented and was measured working. It cannot be exercised
right now because precondition 1 fails: the node emits no HELLO even on a cold
boot with a single handle held throughout (`35-no-hello-after-cold-boot.md`).
The procedure is kept frozen because the sequence itself is not in question.

**Addendum (docs/100):** the tool that implemented this sequence had the switch and
the 9008 grab in two separate processes, which cannot work - the HELLO is spent by the
first opener. `catch` now does both on one handle, and `test_switch_flow.py` checks the
host half of the exchange. The device half still needs a real run.

---

## 4. FEDL — boot-ROM level EDL, by hardware

The only mode that does **not** need the firmware to cooperate, and the only one
that produced a genuine PBL-level session without opening the case.

### The mechanism, from the code

`docs/18-escalation-surfaces.md` §1, verified by disassembly:

```
qusb_dci_dp_gnd_check:
    settle 0x14, then init_dp_gnd (retried up to 3x)
    loop at most 50 iterations, 1 ms apart:
        read the USB PHY register
        if bit 0 is clear -> leave the loop and continue normally
    exit -> "dpGnd LOW, enter FEDL"
```

**The poll window is ~50 ms and runs once, early in USB initialisation.** So the
short cannot be timed into it. It must be **already applied** when the code runs.

### The procedure

```
1. power the tablet OFF completely
2. apply the short: D+ held LOW on the USB connector
3. power ON while the short is held
4. hold it through the whole boot attempt
5. release once the device enumerates as 05C6:9008
```

This is a hold-and-wait, not a race. The precision problem disappears because
the short is simply there when firmware looks.

### What it produced when it worked

```
HELLO ver=3 mode=0        straight from PBL, no crashdump stage
USB\VID_05C6&PID_9008     a new USB instance
```

That is the best state reachable without opening the case.

### Why it then stopped working — the honest reading

`07-dead-ends.md` §D1 records "worked once, never again". Two explanations are
consistent with the evidence, and they are not distinguished:

- **mechanical**: contact was lost, or the short was released before the poll,
  or the short was applied after power-on;
- **the tool consumed the result**: the successful session was followed
  immediately by upload attempts. A `0x29` (`firehose_elf`), a dropped
  connection (`melf`), and no connection at all (`signed_melf`) are three
  different failure points, which is what a session being consumed between
  attempts looks like.

The second is worth taking seriously because it is the same pattern as §2: every
attempt after the first one that touches the port is talking to a device that has
already given its one packet.

### Status: UNVERIFIED — not disproven

This has not been re-attempted with the discipline described above. It is the
only route in this document that does not depend on the thing that is currently
failing, so it is where the next physical attempt should go.

---

## 5. What is NOT a mode

| tried | result |
|---|---|
| key combinations (Vol+, Vol−, Vol+Power, Vol−Power) | no key is read; the ABL never reaches its menu decision point (`07` §D2 correction) |
| `VID_0000&PID_0002` node | a wedged PBL, not a mode (`07` §D3) |
| `SWITCH_TO_STREAM_DLOAD` / `SWITCH_TO_DMSS_DLOAD` | `0x1F`, not implemented on this firmware |
| waiting for a hidden fastboot during the logo | 0.15 ms polling over the entire window found nothing (`05` §5) |
| `EXEC_CMD_GET_TRAINING_DATA` and friends | `0x1F` on 9008; `0x01` on 900E |

---

## 6. Preconditions checklist

Run this before blaming the device. Every item has caused a false failure.

```
[ ] driver is qcwdfserial, not WinUSB      -> a COM port appears in `status`
[ ] no orphaned python process holds it    -> Get-Process python | ? CommandLine -match 'tablet|sahara'
[ ] the node is not a ghost                -> continuously present, not a 14 ms blip
[ ] a HELLO is pending                     -> `selftest` says bytes pending
[ ] the cable did not move mid-session     -> replugging wedges PBL
[ ] the last session did not end in 0x07   -> that is what killed the port before
```
