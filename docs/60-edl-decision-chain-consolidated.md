# The EDL decision chain, consolidated — three gates, and the one that explains "worked once"

Several documents in this session each found one piece of the download-entry logic
(`docs/40`, `48`, `58`, `59`). This one puts them in order, with the addresses and
the property names, so the chain can be read as a whole.

---

    10|## 1. The chain, top to bottom

All of it lives in one function in the XBL core (image[2], around
`0x14831100`–`0x14831xxx`).

```
0x148311e8  movz w0, #0x1
0x148311ec  bl   0x14855fbc          gate 1: some condition, id 1
0x148311f0  cbz  w0, 0x14831214      if zero -> skip
0x148311f4  ... log + return error path

0x14831214  bl   0x148628ac          step
0x1483121c  cbnz w0, <error>

0x14831220  adrp x2, 0x148ab000
0x14831228  add  x2, x2, #0xcf8      "/sw/boot"
0x14831230  bl   0x1484e3b8          look up the /sw/boot node

0x14831244  adrp x1, 0x148ac000
0x1483124c  add  x1, x1, #0x619      "skip_ddr_init_in_EDL"
0x14831254  bl   0x1484ec14          read that property
0x1483125c  ldrh w8, [sp, #0x4]      its value
0x14831260  cmp  w8, #0x2
0x14831264  b.cs 0x148312c4          gate 2: value >= 2 -> skip the EDL work

0x14831268  bl   0x1482e7b8          \  the work that runs when  gate 2 passes
0x14831270  cbnz w0, <error>         |
0x14831274  bl   0x1482e7f8          |
0x14831278  cbnz w0, <error>         |
0x14831280  bl   0x14863494          |
0x14831284  cbnz w0, <error>         |
0x1483128c  bl   0x148262ec          |
0x14831290  cbnz w0, <error>         |
0x14831298  bl   0x1482ed8c          /
...
0x148312e0  bl   0x1482e8a8          sbl1_ddr_set_params
0x148312e4  cbnz w0, <error>
0x148312e8  bl   0x1482c338          step after DDR init
```

and then, separately, `boot_dload_entry` itself at `0x1483130c`:

```
0x14831324  ldrh w9, [x20, #0x80]    gate 3: dload_entry_count
0x14831328  add  w8, w9, #0x1
0x1483132c  strh w8, [x20, #0x80]    increment it
0x14831330  cbnz w9, 0x14831348      non-zero -> skip first-entry-only work
0x14831348  ldrh w8, [x20, #0x80]
0x1483134c  cmp  w8, #0x2
0x14831350  b.cc 0x14831364          count < 2 -> normal path
0x14831360  bl   0x148439ac          the "already entered" path
```

## 2. What each gate is

| gate | address | condition | effect when it fires |
|---|---|---|---|
| 1 | `0x148311ec` | `14855fbc(1)` returns 0 | skips forward, does not log an error |
| 2 | `0x14831264` | `skip_ddr_init_in_EDL >= 2` | jumps to `0x148312c4`, skipping the DDR work |
| 3 | `0x14831350` | `dload_entry_count >= 2` | takes the "already entered" branch |

**Gate 2 on this board:** the DCB declares `skip_ddr_init_in_EDL = 0`. `0 < 2`, so
this gate **does not fire**, and the DDR work runs. That confirms `docs/16` §4.3 by
a different route: the value 0 means *run*, not *skip*.

**Gate 3** is the one `docs/59` identified, and it is the only gate with evidence
that it has actually changed behaviour: the message
`EDL: sbl1_dload_entry: dload_entry_count > 1` is **absent** from the RAM dump, so
the boot that reached EDL was a first entry.

## 3. The property that is not a timeout

`docs/48` established that `check_dp_timeout` is a duration with a
powerdown-or-reset action (`fedl_timeout/action`). Gate 2 here reads a **different**
property, `skip_ddr_init_in_EDL`, and compares it against `2`.

So `docs/40`'s earlier confusion - where a `cmp #0x10` in the forced-download stage
was read as a timeout comparison - and this `cmp #0x2` are two unrelated tests on
two unrelated properties. Keeping them apart matters: one decides *whether DDR is
initialised before the download*, the other decides *what happens when a forced
download times out*.

## 4. What this does to the goal

The goal is `HELLO ver=3 mode=0` from PBL. From the chain:

- **gate 1** and **gate 2** both pass on this board (gate 2 verifiably, from the DCB);
- **gate 3** is the one whose state is unknown but whose *history* is known: the
  working boot was a first entry, so the counter has since been incremented at least
  once.

The single most likely explanation for "ELD worked once and never again" is
therefore **gate 3**, and the only way back past it is for the config block holding
`dload_entry_count` to be re-initialised - which a warm reset does not do
(`docs/59` §4a).

## 5. Honest limits

- Gate 1 is `bl 0x14855fbc` with argument 1; **what it tests is not decoded.** It
  could be a hardware condition, a security state, or a policy flag.
- Gate 3's branch target `0x148439ac` has not been disassembled; it is described
  here as "the already-entered path" because that is what the accompanying message
  says, not because the function was read.
- The ordering above is from address order in one function plus one separate
  function. It is consistent with the two boot logs, but the logs do not show which
  gate was responsible for the difference - they only show that
  `boot_dload_entry` was reached once and not the other time.

The concrete next action remains the one in `docs/59` §6: a **genuine cold boot**,
powered on once, with no warm reset in between, then read the XBL log for
`boot_dload_entry` and for the absence of the counter message.
