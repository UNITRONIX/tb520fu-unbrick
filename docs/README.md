# Documentation index

This directory is organised so you can read only what you need. If you are
holding a bricked `TB520FU` and want to know whether you can still fix it,
read **§1** and **§2** and stop.

---

## Reading order by intent

### "My TB520FU is in the same state — can I fix it?"

1. [`11-faq.md`](11-faq.md) — direct answers, no archaeology.
2. [`05-firehose-and-the-silence.md`](05-firehose-and-the-silence.md) — the exact
   wall, and the two hypotheses for what is behind it.
3. [`09-service-report.md`](09-service-report.md) — what to tell a repair centre,
   and which payloads to hand them.

Everything else is background. None of it will get you write access.

### "I want to understand the protocol work"

1. [`00-glossary.md`](00-glossary.md) — every acronym used anywhere in this repo.
2. [`14-edl-mode-switch.md`](14-edl-mode-switch.md) — getting from crashdump to real
   EDL. Read this first: every session starts here.
3. [`03-sahara-protocol.md`](03-sahara-protocol.md) — the handshake and upload,
   as measured, including the framing bug that cost the most time.
4. [`04-melf-format.md`](04-melf-format.md) — the container, image by image.
5. [`06-signing.md`](06-signing.md) — what qtestsign actually does (less than
   people assume), and why it was not the blocker.
6. [`07-dead-ends.md`](07-dead-ends.md) — 30+ attempts, each with the reason it
   failed. Read this before proposing an idea.

### "I want the story in order"

1. [`01-timeline.md`](01-timeline.md) — chronological, with the state of the
   device at each step.
2. [`session-notes/`](../session-notes/) — the raw session logs, translated
   faithfully from the original Polish, including the wrong conclusions that
   were later corrected.

### "I want to understand the device itself"

1. [`13-hardware-and-drivers.md`](13-hardware-and-drivers.md) — silicon, modules,
   firmware, sensors, and the rooting procedure with measured image sizes.
2. [`00-glossary.md`](00-glossary.md) — including the hardware section: part numbers,
   `lapis`/`lanai`/`pineapple`, GKI, NT36532, FBE, and the rest.

### "I want to port Linux to this tablet"

1. [`12-bootloader-unlock.md`](12-bootloader-unlock.md) — you need an unlocked
   bootloader first, and there is an HTTP endpoint that skips the email flow.
2. [`13-hardware-and-drivers.md`](13-hardware-and-drivers.md) — what hardware you have
   to drive, and which drivers do not survive the trip to mainline.
3. [`08-linux-port-notes.md`](08-linux-port-notes.md) — Fedora, mainline kernel,
   firmware packaging, and what killed the effort.
4. [`10-hardware-notes.md`](10-hardware-notes.md) — why the ROCKNIX ABL seemed
   like a good idea and was not.

---

## Document summary

| File | Contents |
|---|---|
| `00-glossary.md` | Definitions for EDL, PBL, XBL, ABL, Sahara, Firehose, melf, MBN, VIP, AVB, DBC, LUN, and the rest. Start here if any term is unclear. |
| `01-timeline.md` | Dated chronology from unlock to service submission. |
| `02-device-and-partitions.md` | Hardware facts, partition table, `abl_a`/`abl_b` offsets, why both slots matter, the slot-retry counter. |
| `03-sahara-protocol.md` | Packet layout, HELLO variants, READ_DATA loop, END/DONE, the NAK codes observed, framing and ZLP. |
| `04-melf-format.md` | The ELF32 wrapper plus five internal images, offsets, entries, the hash-table mystery. |
| `05-firehose-and-the-silence.md` | The core finding: accepted programmer, absent endpoint. Includes the measurement methodology. |
| `06-signing.md` | qtestsign internals, the `0x29`/`0x21`/`0x23` distinction, why signing was a red herring. |
| `07-dead-ends.md` | Every failed approach, with a one-line reason. |
| `08-linux-port-notes.md` | Kernel/DT/Fedora work, RAM-boot results, firmware inventory, TWRP assessment. |
| `09-service-report.md` | English translation of the report given to the repair centre, plus the payload manifest. |
| `10-hardware-notes.md` | ROCKNIX ABL substitution analysis, GPIO mismatch, qtestsign acceptance by XBL. |
| `11-faq.md` | Twenty short questions and answers. |
| `12-bootloader-unlock.md` | The HTTP unlock endpoint: URL format, file contents, per-serial signing, unlocking procedure and caveats. |
| `13-hardware-and-drivers.md` | Complete hardware inventory: SoC naming, 340 kernel modules, board-specific drivers, firmware blobs by subsystem, storage layout, and the exact Magisk rooting procedure. |
| `14-edl-mode-switch.md` | The 900E → 9008 transition: the working sequence with log evidence, seven variants including those that failed, timing, and eight pitfalls. |

---

## Conventions used in these documents

- **Measured** means we have a log line for it. **Inferred** means we reasoned
  from code or strings. Every claim is labelled.
- Hex values are written `0x29`. Sizes are written with thin spaces for
  readability: `1 554 996 B`.
- Error codes are Sahara NAK values unless stated otherwise. The full table is in
  [`03-sahara-protocol.md`](03-sahara-protocol.md) and in
  [`scripts/sahara_codes.py`](../scripts/sahara_codes.py).
- Commands and paths from the original sessions have been rewritten to
  placeholders (`<ROM_DIR>`, `<DEVICE_SERIAL>`) so they are safe to publish and
  portable between machines.
- Where an earlier note reached a conclusion that later evidence overturned, the
  correction is shown in place, marked **CORRECTION**, rather than silently
  edited. The wrong turns are the useful part.
