# Documentation index

This directory is organised so you can read only what you need.

**If you are holding a bricked TB520FU right now, read in this order:**

    1.  `73-session-consolidation.md`   - the current state in one page, and the one route left
    2.  `87-current-blocker-needs-a-physical-action.md` - what to do next, and what is not possible from a PC
    3.  `82-sibling-recovered-and-firehose-works-on-this-model.md` - proof the device is recoverable
    4.  `88-the-battery-disconnect-procedure.md` + `90-official-service-manual-found.md` - the documented recovery path
    5.  `07-dead-ends.md` - everything already tried, so you do not repeat it

Everything else is background.

---

## Reading order by intent

### "My TB520FU is in the same state - stuck at 900E, no HELLO. What do I do?"

| # | document | why |
|---|---|---|
| 1 | `73-session-consolidation.md` | the whole picture in one page |
| 2 | `87-current-blocker-needs-a-physical-action.md` | the current blocker, and the tools that exist |
| 3 | `82-sibling-recovered-and-firehose-works-on-this-model.md` | a sibling recovered; Firehose confirmed working on this model |
| 4 | `88-the-battery-disconnect-procedure.md` | the recovery step this project never performed |
| 5 | `90-official-service-manual-found.md` | Lenovo's own SOP, tool list, battery part number |
| 6 | `11-faq.md` | short answers |

### "I want to understand why the programmer never starts"

| # | document |
|---|---|
| 1 | `05-firehose-and-the-silence.md` - the observation and every alternative excluded |
| 2 | `20-entry-point-spin.md` - the entry stub returns without checking its result |
| 3 | `16-firehose-bringup.md` - the DDR pipeline, and the bypass that exists |
| 4 | `57-two-boot-logs-and-ddr-recovery.md` - the device's own record: DDR init has failed here before and recovered |
| 5 | `56-xbl-boot-log-is-in-the-dump.md` - the boot log, in plain text, inside a capture you may already have |

### "I want to understand the protocol work"

| # | document |
|---|---|
| 1 | `00-glossary.md` - every acronym |
| 2 | `14-edl-mode-switch.md` - 900E to 9008, measured, with pitfalls |
| 3 | `03-sahara-protocol.md` - the handshake and upload as measured |
| 4 | `04-melf-format.md` - the five-image container, dissected |
| 5 | `34-hello-is-first-opener-wins.md` - one HELLO per boot; and why a `SAHARA_RESET` destroys the port |
| 6 | `06-signing.md` - what qtestsign does and does not do |
| 7 | `07-dead-ends.md` - 30+ attempts, each with the reason it failed |

### "I want to know what the download-entry code actually does"

| # | document |
|---|---|
| 1 | `40-xbl-stage-table.md` - the boot chain by name and address |
| 2 | `60-edl-decision-chain-consolidated.md` - the three gates, in order |
| 3 | `41-fedl-entry-condition.md` - the D+ condition, reduced to one bit |
| 4 | `69-the-request-is-bit-12.md` - the download request bit |
| 5 | `70-bit-12-is-never-set-in-xbl.md` and `71-tz-owns-the-register-but-has-no-setter.md` - why it cannot be set |
| 6 | `65-the-edl-cookie-in-uefiplat-cfg.md` - the vendor's own config, stating the cookie |
| 7 | `79-dp-toggle-decoded.md` - the D+ toggle, from constant to register writes |

### "I want to understand the device itself"

| # | document |
|---|---|
| 1 | `13-hardware-and-drivers.md` - silicon, modules, firmware map, rooting |
| 2 | `45-live-dt-usb-hardware.md` - USB PHY addresses, `gpio29`, key wiring |
| 3 | `47-keys-are-on-three-controllers.md` - which key is read by which hardware |
| 4 | `63-the-live-memory-map.md` - the 53-region table, read from the device |
| 5 | `02-device-and-partitions.md` - partition table, slots, ABL offsets |

### "I want to port Linux to this tablet"

| # | document |
|---|---|
| 1 | `12-bootloader-unlock.md` - unlock over HTTP, no email flow |
| 2 | `13-hardware-and-drivers.md` |
| 3 | `08-linux-port-notes.md` - and what killed the effort |
| 4 | `10-hardware-notes.md` - why the ROCKNIX ABL substitution was the mistake |

---

## Corrections that matter

Several early conclusions were overturned. These are the ones worth knowing before trusting
anything older:

| old claim | corrected by | what is true |
|---|---|---|
| `DDR_DATA` is unreachable (dump order blocks it) | `33-ddr-data-is-reachable.md` | it is reachable; the vendor tool orders by size, not address |
| the device boot-loops on its own | `23-no-boot-loop.md` | it waits in 900E; our own resets cycled it |
| a `SAHARA_RESET` is harmless hygiene | `34-hello-is-first-opener-wins.md` | it destroys the port 16 ms later |
| CS0 only serves 40 MiB, so DRAM is suspect | `36`, `46` | training covers 8x2 GiB; the 40 MiB edge is `qdss_region` |
| the branch at `0x1482eb14` means "skip training" | `37-branch-sense-correction.md` | the sense was inverted |
| no `eud` node exists, so EUD is closed | `74-eud-node-does-exist.md` | it exists, `status = "okay"`, in the Android DTB |
| the captured boot loaded stock UEFI | `67` then `68` | it loaded ROCKNIX; and EDL does not need UEFI at all |
| the PMIC dump holds register state | `44` | it is a header plus a scattered log, 99.4 % zero |

## Conventions used in these documents

- **Measured** means there is a log line or a command output for it. **Inferred** means
  reasoning from code or documents. Every claim is labelled.
- Hex values are written `0x1FD9000`. Sizes use thin spaces: `1 554 996 B`.
- Where an earlier note was wrong, the correction appears in place, marked **CORRECTION**,
  rather than being silently edited. The wrong turns are the useful part.
- Rules for working in this repository: `32-session-conventions.md`.
