# The cheapest experiment has never been run: a real discharge

Everything in this session stopped at the same wall, and the wall is not where the documents
said it was.

---

## 1. The finding

Every power cycle in this project's history has been a **key-hold reset**. Not one has been a
genuine power-off. That is not a supposition - the repository says so in four places and
lists the consequences:

| consequence of a key-hold reset | document |
|---|---|
| `dload_entry_count` is preserved across it | `docs/59` §4a |
| the TCSR cookie at `0x1FD9000` never clears (always-on domain) | `docs/68` §4 |
| the EUD flag at `0x088E2000` never clears (always-on block) | `docs/74`, `docs/80` |
| no genuine off state has ever been observed on this unit | `docs/51` |

And `docs/42` carries the line that decides the priority:

```
| a discharge restores the HELLO | **NOT tested** |
```

Still not tested. A search of every document and session note for a completed discharge
returns nothing - the phrase appears only as a recommendation, never as a result.

## 2. Why this outranks everything else that was done today

The three routes ranked in `docs/42` all assume the device's persistent state is what it is.
But three separate blockers - the counter, the cookie, the EUD flag - live in blocks that a
key-hold reset provably does not clear. If those blocks are what is holding the device in
900E with a spent HELLO, then **no amount of host-side work changes anything**, which is
exactly what this session measured over and over: an accepted IOCTL that did nothing, a port
that reports `DeviceEnumerated` with a null descriptor, a node that returns to the same
wedge.

Meanwhile the one action that clears all three at once has never been performed:

```
1. unplug the USB cable
2. hold Power 20-30 s until the screen is dark
3. leave it unpowered for 30-60 minutes
4. plug back in, no keys held
```

Cost: half an hour of waiting, nothing else. Risk: none - it is the least invasive action
available short of opening the case.

## 3. What this session did instead, and why that was reasonable

Today produced: the two-process bump defect (`docs/100`), the hub theory retired (`docs/99`),
the host-side routes measured and closed (`docs/102`, `docs/103`), the per-socket driver
binding (`docs/105`), and the preflight and ledger that make an attempt verifiable
(`docs/106`, `docs/104`).

Every one of those is a real improvement to the method. None of them is the experiment. The
honest reading is that a great deal of useful engineering happened around a step that was
never taken, because that step requires somebody to physically leave the tablet alone for
half an hour - and the work in front of a keyboard kept looking more urgent.

## 4. The tool, so the wait is measured rather than assumed

`scripts/wait_disconnect.py` times it and refuses to accept a fake:

```
python scripts/wait_disconnect.py --minutes 30 --expect-plug
```

- it starts the clock only once the tablet has genuinely left the bus;
- if the device re-enumerates **during** the window, it decides `that is a RESET, not an off
  state` and stops - a device with no power cannot come back on its own, so its return proves
  the battery is still feeding the always-on domain;
- at the end it reports the verified absence and prints the single next command.

The distinction matters because the difference between "off" and "reset" has been the whole
ambiguity. `docs/51` recorded that no genuine off state had ever been observed; this makes
that observable from the host without trusting anyone's memory of how long they held a
button.

## 5. What I cannot do

I cannot unplug the cable or hold the power button. This is the same boundary `docs/87` ran
into, and it has now been reached from a different direction: not "the device needs a
physical action" but "**the one physical action that addresses the persistent state has never
been tried.**"

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

But the next step is not another measurement. It is 30 minutes of the tablet sitting
unplugged, and then one command.
