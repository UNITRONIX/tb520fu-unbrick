# Status snapshot, 2026-11-11 13:13 — nothing has changed, and here is what that means

A short factual snapshot rather than another analysis. Repeated checks of an unchanged state
should not generate new documents; this one exists only because the session has accumulated
enough that the current position needs to be unambiguous.

---

## 1. Verified right now

```
tablet.py status
  VID_05C6 nodes : none
  COM ports      : COM1 only

PnP
  USB\VID_0000&PID_0002\9&1FF60AC4&0&4   Error, Code 43
  hardware id    : USB\DEVICE_DESCRIPTOR_FAILURE
  parent         : generic USB 2.0 hub, VID_1A40 PID_0101
```

The device is on the bus and cannot deliver a device descriptor. It has been in exactly this
state since 13:00.

## 2. What the goal requires, restated without decoration

**`HELLO ver=3 mode=0` from PBL.** Not a dump, not a crashdump session - a genuine EDL
session with the packet that says `version 3, mode 0`.

To reach it, XBL has to take one of two branches (`docs\75`):

```
EUD active          -> forced-EDL path, no short needed
D+ condition seen   -> forced-EDL path after the poll
```

Both conditions live in registers that the crash handler does not expose (`docs\80`), and
nothing readable sets them (`docs\70`, `docs\71`). What remains is to make the hardware
present the condition at power-up, which is a physical act.

## 3. What has been ruled out, so it is not retried

| approach | status | document |
|---|---|---|
| cookie -> `boot_dload_entry` | no readable code sets bit 12 | `70`, `71` |
| bump 900E -> 9008 | the node emits no HELLO | `34`, `35` |
| EUD via DT property | declared, but flag unsettable and unreadable | `74`, `80` |
| key combinations (Vol+, Vol-, with Power) | code that reads them never runs | `47`, `07` §D2 |
| EDL cable / D+ short | **not closed** - needs a physical short and a pin-out | `41`, `81` |
| test point + battery disconnect | **not closed** - the documented sibling recovery | `88`, `90` |

The last two rows are the only open ones, and both are physical.

## 4. What is prepared for the moment the device responds

Nothing further needs to be written before an attempt:

| tool | purpose | tested |
|---|---|---|
| `tablet.py status` / `selftest` | what is on the bus, and the whole chain | yes |
| `tablet.py catch` | hold one handle across a power cycle, grab the HELLO | yes |
| `tablet.py read` / `bump` | memory read / 900E -> 9008 | needs a HELLO |
| `vendor_entry.py` | Lenovo's card, with per-step verification | yes |
| `ab_test.py` | control vs test for the volume-key question | yes |

## 5. The single most useful next action

Unchanged, and it is not a document:

```
1. connect the tablet DIRECTLY to a rear USB 2.0 port - no hub (docs/91)
2. unplug, hold Power 20-30 s, plug in with no keys   <- clears the current wedge
3. if it returns as 900E, run:  python scripts/ab_test.py --run control
4. then run:                    python scripts/ab_test.py --run test
```

Step 3 gives the control the previous attempt lacked (`docs\86`). Step 4 is the only
untested key combination (`docs\84`).

If both give `900E`, the keys do nothing and the remaining option is the physical route:
a D+ short at the connector, or the battery-disconnect procedure with the manual in hand.

## 6. Honest summary

The goal is not achieved, and nothing in this session moved the device any closer to `9008`.
What the session produced is an accurate map of why, with the hardware cleared of fault and
three of four routes provably closed.

**Every remaining step needs a hand on the device.** Until then, repeated checks will keep
returning the two lines in §1.
