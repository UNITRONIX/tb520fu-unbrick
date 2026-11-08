# Session notes index

Raw session logs, translated from the Polish originals. These are **not** rewritten
for clarity — they keep the structure, the numbers, the ordering and the mistakes of
the moment they were written. Where a later session corrected an earlier conclusion,
that is noted in [`../docs/01-timeline.md`](../docs/01-timeline.md), not retro-edited
here.

The value of these files is exactly that they are unpolished: they show which lines
of reasoning were being pursued, and how long a wrong assumption can survive.

Device serials and host paths have been replaced with `<DEVICE_SERIAL>`,
`<HOST_USER>` and `<ROM_DIR>`.

---

## Chronological

| File | Date | Original (Polish) title |
|---|---|---|
| [`2026-11-03-session-summary.md`](2026-11-03-session-summary.md) | Nov 3 | Fedora port session summary (written in English) |
| [`2026-11-05-manifest.md`](2026-11-05-manifest.md) | Nov 5 | `MANIFEST.txt` |
| [`2026-11-06-evening.md`](2026-11-06-evening.md) | Nov 6 | `NOTES_ODKRYCIA_2026-11-06_wieczor.md` |
| [`2026-11-07-gates.md`](2026-11-07-gates.md) | Nov 7 | `NEW_CHAT_PROMPT.txt` + gate logs |
| [`2026-11-07-linux-gate.md`](2026-11-07-linux-gate.md) | Nov 7 | `STATUS_TERAZ_LINUX_SYNC.txt` |
| [`2026-11-08-night.md`](2026-11-08-night.md) | Nov 7–8 | `NOTES_ODKRYCIA_2026-11-08_noc.md` |
| [`2026-11-08-morning.md`](2026-11-08-morning.md) | Nov 8 | `SESSION_2026-11-08_MORNING.md` |
| [`2026-11-08-evening.md`](2026-11-08-evening.md) | Nov 8 | `SESSION_2026-11-08_EVENING.md` |
| [`2026-11-08-melf-dead-end.md`](2026-11-08-melf-dead-end.md) | Nov 8 | `MELF_DEAD_END.md` |
| [`2026-11-08-melf-repacker.md`](2026-11-08-melf-repacker.md) | Nov 8 | `MELF_REPACKER.md` |
| [`2026-11-08-device-degradation.md`](2026-11-08-device-degradation.md) | Nov 8 | `DEVICE_DEGRADATION.md` |
| [`2026-11-08-signing.md`](2026-11-08-signing.md) | Nov 8 | `QTESTSIGN_SIGNING.md` |
| [`2026-11-08-abl-substitution.md`](2026-11-08-abl-substitution.md) | Nov 8 | `ABL_SUBSTITUTION_ANALYSIS.md` |
| [`2026-11-08-status-and-procedure.md`](2026-11-08-status-and-procedure.md) | Nov 8 | `STATUS_PO_RESTARCIE.md`, `RANO_CZYTAJ_MNIE.md`, `STATUS_TERAZ*.txt`, `JUZ_NOTE_PL.txt` |
| [`2026-11-08-service-report-pl.md`](2026-11-08-service-report-pl.md) | Nov 8 | `SERWIS_KROKI.txt`, `SERWIS_KROTKO.txt`, `SERWIS_OPIS_USTERKI.txt` (Polish verbatim + translation) |

---

## Note on fidelity

Three translations deserved special care because they carry the technical core:

- `2026-11-08-night.md` — contains the fourteen numbered discoveries. Every figure,
  offset and error code is preserved exactly as recorded.
- `2026-11-08-signing.md` — contains the qtestsign reasoning and its refutation.
- `2026-11-08-service-report-pl.md` — this one is kept in the original Polish side
  by side, because it is the document a repair centre actually reads, and the
  wording matters more than the language.

Some of these notes contain conclusions that are **wrong** — for example the
`0x21` "signature rejection" interpretation in `2026-11-08-device-degradation.md`,
which was later shown to be an artefact of an interrupted transfer. They are left
uncorrected in place, with a **CORRECTION** marker, because the sequence of being
wrong and then finding out is the useful content.

