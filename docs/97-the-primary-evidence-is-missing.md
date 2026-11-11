# The primary evidence is missing from the repository

While looking for a log that showed a successful `HELLO ver=3 mode=0`, I checked whether the
logs the documentation cites still exist. **They do not.**

---

## 1. What is claimed versus what is present

Documents throughout this repository cite specific log files as the evidence for their
conclusions:

| cited log | cited in | present in repo? |
|---|---|---|
| `banner_capture.log` | `docs\14` §V1b, `docs\03` | **missing** |
| `catch2.log` | `docs\14` §2, §6 (verbatim excerpt) | **missing** |
| `post_done_disconnect_2026-11-10.log` | `docs\15` §5 | **missing** |
| `upload_compare` output | `docs\07`, `scripts\README.md` | **missing** |
| any log containing `HELLO ver=3 mode=0` | the whole premise | **not found anywhere** |

Searching every `.log`, `.txt`, `.jsonl` and `.md` file under 2 MB in the repository for
`ver=3 mode=0` or `HELLO ver=3` returns **only prose** - documents *asserting* that the state
was reached. There is no raw capture to check the assertion against.

## 2. Why this matters

The repository's central claim is:

> Sahara accepts the signed programmer, `END 0x0`, `DONE` acknowledged - and then the device
> never speaks.

Every conclusion in `docs\05`, `docs\16`, `docs\20` and `docs\42` rests on that sequence
having been observed. The only surviving form of the observation is the prose. The log it came
from was deleted or never committed.

**This is not an accusation that the observation did not happen.** `docs\14` §6 reproduces
`catch2.log` inline with millisecond timestamps and interleaved READ offsets - detail that is
hard to fabricate and consistent with everything else measured since. The session notes in
`session-notes/` also survive.

It is a statement about *verifiability*: a reader cannot independently confirm the founding
measurement, and a future attempt cannot diff its behaviour against the original run.

## 3. What was deleted, and when

Two likely causes, both visible in the repository:

- `scripts\_superseded/` holds eight catcher scripts whose output went to files in `scripts\`
  (this session's own `hello_catch.txt`, `pid_watch.txt`, `grab.log` are still there) - older
  runs of those were cleaned up;
- `docs\30` §5 records an earlier cleanup that **destroyed evidence**: "During cleanup, the
  16 GB of dump files were deleted before the 260 MiB of real content from `DDRCS1_0` had been
  extracted - a path bug in the cleanup script."

So cleanup removing primary data is a documented pattern here, not a one-off.

## 4. What this changes about the session's own work

Everything measured **today** was written to disk and committed:

```
scripts\tablet_sessions.jsonl      append-only, now deduplicated and compacted
com_attempt\DDRCS0_0_first40MB.bin 40 MiB of real memory, committed
com_attempt\real_content\         272 MB of extracted content
scripts\crash_region_probe\       44 region samples
scripts\pon_probe\                3 PMON_HIS captures
docs\56-xbl-boot-log-is-in-the-dump.md   the boot log, quoted in full
```

That is a deliberate difference from how the early material was handled, and the reason
`docs\32`'s conventions matter: a claim without its capture is an opinion with a timestamp.

## 5. The honest consequence

The founding measurement of this project - `HELLO ver=3 mode=0`, then silence after `DONE` -
is **supported by consistent, detailed prose and by everything measured since, and not by a
raw capture in the repository.**

Anyone re-examining this work should treat that claim as *well-corroborated but not
independently checkable*, and should capture their own run rather than trusting the description.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained in this session.** Device currently off the bus
(`docs\87`, `docs\92`).

No code change accompanies this document. It is a record of a finding about the evidence base
itself, which belongs in the repository for the same reason `docs\07` does: knowing what is
*not* verifiable is part of knowing what is true.
