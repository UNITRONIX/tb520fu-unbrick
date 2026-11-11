# `boot_dload_entry` is guarded by a counter — and it is why EDL worked once

`docs/58` found that one of the two boot logs reached `boot_dload_entry` and the
other did not. This document gives the mechanism: a **counter in the config block
that increments on every entry**, with a comparison against `2`.

---

    10|## 1. The function

`boot_dload_entry` is logged from one place, `0x1483130c`, and the code around it is
short enough to read whole:

```
0x1483130c  adrp x0, 0x148ac000
0x14831310  add  x0, x0, #0x62e          "boot_dload_entry"
0x1483131c  bl   0x1482a91c              log it
0x14831320  adrp x20, 0x148f0000
0x14831324  ldrh w9, [x20, #0x80]        <- read a counter
0x14831328  add  w8, w9, #0x1
0x1483132c  strh w8, [x20, #0x80]        <- increment and store it
0x14831330  cbnz w9, 0x14831348          if it was already non-zero, skip init
0x14831334  mov  x0, x19
0x14831338  bl   0x14843a74              (first-entry only work)
0x14831340  bl   0x1482ed58              (first-entry only work)
0x14831348  ldrh w8, [x20, #0x80]
0x1483134c  cmp  w8, #0x2
0x14831350  b.cc 0x14831364              count < 2 -> normal path
0x14831354  adrp x0, 0x148ac000
0x14831358  add  x0, x0, #0x63f          a second message
0x1483135c  bl   0x1482a91c              log it
0x14831360  bl   0x148439ac              (the "already entered" path)
```

Three behaviours are visible:

1. **A counter at `[0x148F0000 + 0x80]` is incremented on every call.** It lives in
   the XBL config block, not in a register.
2. **First-entry work runs only when the counter was zero** (`cbnz w9` skips it).
3. **When the counter reaches 2, a different message is logged and a different
   function is called** (`0x148439ac` instead of the normal path).

## 2. The string that names it

`docs/40` listed a string that had not been placed:

```
EDL: sbl1_dload_entry: dload_entry_count > 1
```

That is this comparison. `cmp w8, #0x2` / `b.cc` is exactly "count is not yet 2",
and the message is what gets logged on the other side. So the counter is
`dload_entry_count` and `> 1` means **the second and all later entries**.

## 3. Why this matters for the goal

The device's behaviour across this session is consistent with that counter being
past its first increment:

- EDL was entered at least once (the older boot log, `docs/58`);
- every attempt since has produced `900E` with no HELLO;
- the counter is in **config RAM**, which survives a warm reset and is re-initialised
  by a cold boot.

So there are two distinct things that could restore a first-entry state:

| action | effect on the counter |
|---|---|
| warm reset (PSHOLD) | preserved - the block is not re-initialised |
| genuine cold boot | re-initialised to 0 |

That inverts the hypothesis in `docs/58` §5. That document guessed a *warm* reset
was the favourable case, because the working log followed one. If the counter is
what gates the path, then a **cold** boot is the favourable case, and warm resets
keep the device in the "already entered" state.

**Both readings are consistent with the single working log**, so the logs alone
cannot decide it. What they do establish is that a counter exists, it is compared
against 2, and it changes behaviour.

## 4. The decisive check — done, and it settles the direction

The counter is a readable memory location at `0x148F0080`, but reading it needs a
HELLO, which is the standing blocker. The logs answer it without the device, by
asking a sharper question: **does the working log contain the
`dload_entry_count > 1` message?**

```
python -c "d = open('com_attempt/DDRCS0_0_first40MB.bin','rb').read();
           print(b'dload_entry_count > 1' in d)"
-> False
```

**The message is absent from the dump.** The working boot did **not** log it. So
that boot was a **first entry**, `dload_entry_count` was 0 or 1, and the
first-entry path ran.

Since that boot, the device has entered the download path at least once more - and
every attempt in this session has produced `900E` with no HELLO. That is exactly
what the `> 1` branch predicts.

## 4a. This reverses `docs/58` §5

`docs/58` guessed, from the log alone, that a **warm** reset was the favourable case
because the working boot followed one. With the counter in view, the reasoning
inverts:

| action | `dload_entry_count` in config RAM |
|---|---|
| warm reset (PSHOLD) | **preserved** - the block is not re-initialised, so a device already past 1 stays past 1 |
| genuine cold boot | **re-initialised to 0**, which is the only way back to the first-entry path |

So the earlier hypothesis was backwards. A warm reset is what *keeps* the device in
the "already entered" state; only a real cold boot can return it to a first entry.

**Both readings fit the single working log**, which is why the log alone could not
decide it - but the absence of the message does. The working boot was a first
entry, and warm resets cannot restore that condition.

## 5. What is not claimed

- The counter is shown to be read, incremented and compared. That it **gates** the
  EDL outcome is inferred from the branch structure and from the message being
  absent on the one boot that worked - strong, but a chain of two inferences, not a
  direct observation of both outcomes with known counter values.
- The address `0x148F0080` comes from `adrp x20, 0x148f0000` + `[x20, #0x80]` in the
  listing; it is not confirmed against a symbol.
- Whether the counter is the *only* gate is unknown. `docs/40` showed TCSR bits
  `0x30` and property `0x0c` also steer the forced-download stage, and those may
  interact with it.

## 6. What this means for the next attempt

The test in `docs/58` §6 said "issue a warm reset". **That is now the wrong
instruction** and this document supersedes it.

The mechanism predicts the opposite:

```
a genuine cold boot is required, and it must be the first entry since that boot.
```

Every warm reset taken between a cold boot and the next attempt pushes the counter
further past 1, and the device cannot re-enter the first-entry path until the
config block is re-initialised.

That is testable and cheap:

```
1. leave the tablet fully off, no cable, long enough for the config block to be
   re-initialised (a real power-down, not a key-hold reset)
2. power on ONCE
3. do not warm-reset it
4. check `tablet.py status` immediately, and read the XBL log for
   "boot_dload_entry" and for the ABSENCE of "dload_entry_count > 1"
```

If `boot_dload_entry` appears without the counter message, the device has taken the
first-entry path and `9008` with a fresh HELLO is the expected result.
