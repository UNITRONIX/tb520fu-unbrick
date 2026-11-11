# Where the session ended: what is proven, what is open, and what would unblock it

A consolidation document. Twenty-two notes were written in one session
(`docs/33`–`docs/72`, plus corrections to `16`, `30`, `58`). This is the short version
for whoever picks this up next.

---

## 1. The goal and its state

**Goal:** obtain `HELLO ver=3 mode=0` from PBL on the TB520FU - a genuine EDL session,
not a crashdump one.

**State at end of session, verified against the device:**

```
tablet.py selftest
  VID_05C6 enumeration      PASS   1 node (PID_900E)
  Qualcomm COM port         PASS   COM10
  bytes pending             FAIL   0 - no HELLO at any baud rate
  memory table cached       FAIL
  programmer on disk        PASS   1 569 028 B
```

**Not achieved.** The device presents as `900E` and stays silent.

## 2. What this session proved

| finding | document | evidence class |
|---|---|---|
| `DDR_DATA` is reachable; the vendor tool's dump order is by size, not address | `33` | measured, from the tool's own log |
| The Sahara HELLO is first-opener-wins; `SAHARA_RESET` does not produce another and destroys the port | `34` | measured, 6 sessions + vendor-tool control |
| DDR training describes all eight 2 GiB windows - DRAM is not the fault | `36` | measured, from `DDR_DATA` |
| The 40 MiB boundary is the start of `qdss_region`, not a capacity limit | `46` | measured, live DTB |
| FEDL entry is `(status & 0x30000) == 0x10000` - one bit, no duration | `41` | disassembly, offset verified |
| EUD entry is bit 0 of `0x088E2000`; no DTB property enables it | `42` | disassembly + 4 393 properties searched |
| Volume Up is PM8550 gpio6 (needs a driver); Power and Vol-Down are PON | `47` | live DTB |
| XBL runs to completion and loads APPSBL | `56` | device's own boot log |
| The boot that reached EDL never loaded APPSBL - **EDL does not need UEFI** | `68` | two boot logs compared |
| The download cookie is `0x1FD9000`, value `0x10` = full dump | `65` | vendor's `uefiplatLA.cfg` |
| The request bit is bit 12 of that register | `69` | disassembly |
| **No readable code sets bit 12** - not XBL, not TZ | `70`, `71` | exhaustive search of both |

## 3. What is now closed, and why

| route | blocker | closed by |
|---|---|---|
| cookie → `boot_dload_entry` | bit 12 cannot be set by any readable code | `70`, `71` |
| bump 900E → 9008 | the node emits no HELLO; reset does not restore it | `34`, `35` |
| EUD | needs a debug policy no DTB declares | `42` |
| key combinations | keys are read by code the foreign ABL never runs | `47`, `07` §D2 |

**One route is open: FEDL by hardware short.**

## 4. Why FEDL is the one that is left

It is the only entry path that:

- runs **before** DDR init in the stage table (`docs/40`), so it does not pass through
  the stage where the programmer dies;
- does **not** need a HELLO (`docs/34`);
- does **not** need the download cookie (`docs/71`);
- does **not** need the ABL, UEFI, or a handoff (`docs/68`);
- depends only on a latch bit that a physical short can set **before** the firmware
  looks (`docs/41`).

Its single blocker is that **no document in our possession gives this model's Type-C
pin-out.**

## 5. The three things that would move this forward

None can be produced by analysing the files we hold:

1. **A verified Type-C pin-out for the TB520FU.** Then `docs/41` §5's procedure can be
   attempted: D+ held low before power, released after `9008` appears.
2. **A genuine cold boot**, powered on once, no warm reset - the only thing that can
   return `dload_entry_count` (`docs/59`) to a first-entry state.
3. **A charged battery.** `VBAT 3588mV` and `UFS Gear 1 due to low battery` appear in
   both captured boots. `docs/07` §E1 established this degrades transfers in
   confusing ways; removing it costs nothing.

## 6. The tooling to use, and the tooling to ignore

Use **`scripts/tablet.py`** - `status`, `selftest`, `wait`, `read`, `bump`, `catch`,
`watch`, `offcheck`. Use **`scripts/vendor_entry.py`** for the manufacturer's
procedure with per-step verification.

`scripts/_superseded/` holds eight catchers written earlier in the session. They are
kept for the record and **must not be used** - they differ in timing model, and that
difference is what made a working method appear to stop working.

**Two rules that cost real time to learn** (`docs/32`):

- never pipe a live script into `Select-Object -First` / `head` - it kills the process
  mid-run, and on this project that means killing a tool while it holds the COM port;
- never `SAHARA_RESET` at the end of a session. It re-enumerates the interface and the
  node vanishes 16 ms later, which reads exactly like a device fault.

## 7. Honest summary

The tablet is not fixed. What changed is that the obstacle is no longer vague: the
hardware is not faulty, the boot chain runs, the download path exists and has been
taken once on this device, and the one gate left is a register bit that nothing
readable can set.

**What is left needs a wire, not another document.**
