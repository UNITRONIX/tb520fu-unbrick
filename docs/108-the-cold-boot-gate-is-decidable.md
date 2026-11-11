# The cold boot is the gate, and the boot log can decide it

`docs/59` §6 named a cheap experiment. `docs/61` narrowed the mechanism to one variable.
This session found the last piece needed to make the experiment *decidable* rather than
hopeful: the device's own boot log says whether the cold boot worked.

---

## 1. The mechanism, in one variable

From `docs/59` and `docs/61`, the EDL decision has exactly one remaining variable:

```
dload_entry_count  at 0x148F0080      ldrh, compared against 2
```

- incremented on every entry into `boot_dload_entry`;
- its block is **preserved across a warm reset** and **re-initialised by a genuine cold
  boot**;
- the one boot that reached EDL did so without logging the `> 1` message, i.e. it was a
  first entry.

So the requirement is not "power cycle the tablet". It is: **a first entry since the block
was last initialised**, which means a real power-down and one power-on with no warm reset in
between.

## 2. Why this matters more than it looks

Three of this project's open blockers live in persistent blocks:

| blocker | block | cleared by |
|---|---|---|
| `dload_entry_count` | `0x148Fxxxx` config block (`docs/59`) | cold boot |
| TCSR cookie `0x1FD9000` bit 12 | always-on domain (`docs/68`) | real power removal |
| EUD flag `0x088E2000` | always-on block (`docs/74`) | real power removal |

A key-hold reset provably does not clear any of them, and **every attempt in this
project's history has been a key-hold reset** (`docs/107`). So one action addresses the
whole set, and it is the only untested one.

## 3. The new part: the experiment is now decidable

`docs/59` §6 says to read the XBL log for `boot_dload_entry` and for the absence of the
counter message. That was a manual procedure. `scripts/cold_boot_check.py` does it:

```
python scripts/cold_boot_check.py --dump com_attempt/DDRCS0_0_first40MB.bin
```

Run against the capture this repository already has, it reproduces `docs/58` without being
told what to find:

```
2 XBL log(s) found

--- log 1 at 0x1a00000 (7968 B) ---
  TCSR reg value         0x10
  RamDump loaded         890156 B
  boot_dload_entry       present
  counter > 1 warn       -
    FIRST-ENTRY PATH: reached with no counter warning

--- log 2 at 0x1ce4000 (16454 B) ---
  TCSR reg value         -
  RamDump loaded         0 B
  boot_dload_entry       -
  counter > 1 warn       -
    crashdump path - no 9008 by design
```

That is `docs/58` §1 exactly: one warm-reset boot that entered EDL, one shutdown boot that
loaded 0 bytes and did not. Independent confirmation of the analysis, from the bytes.

**A bug worth recording.** The first version searched for one log header and stopped. It
found log 1, printed a confident verdict, and silently omitted log 2 - the half of the
evidence the whole finding rests on. Both logs exist in the SAME dump at different
addresses, and a scanner that returns "the log" instead of "the logs" would have hidden the
comparison while appearing to confirm it.

## 4. What the next attempt should be, precisely

```
1. unplug the cable
2. hold Power 20-30 s until the screen is dark
3. leave it unpowered 30-60 minutes      <- clears the always-on blocks
4. plug into the SAME socket              <- docs/105: it is bound to qcwdfser
5. hold NOTHING                           <- docs/99: Vol+ is 0 for 2
6. python scripts/tablet.py catch --seconds 180
```

Step 3 is the part that has never been done. Steps 4-6 are checked by `preflight.py`.

If it works, the ledger (`docs/104`) records the success together with the raw HELLO packet,
and a second run of the same procedure makes it *repeatable* in the sense the goal requires.

If it does not, the boot log becomes the next thing to read - not the guesswork. A
`crashdump path` verdict after a genuine 30-minute discharge would mean the persistent state
is not what is blocking entry, and the FEDL route (b) moves to the front.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.**

New: the gate for the cold-boot experiment is measurable from a dump the repository already
holds, and that dump confirms the mechanism's expected signature. What is missing is the
experiment itself - a tablet left without power for half an hour.
