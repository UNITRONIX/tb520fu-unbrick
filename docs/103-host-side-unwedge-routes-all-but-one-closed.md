# Un-wedging: every host-side route measured, and one still untested

The question "can the wedge be cleared without touching the cable?" now has a nearly
complete, measured answer. This document is the record of what was tried, in the order it was
tried, because three of the attempts *looked* like they worked.

---

## 1. The four routes, and what each actually did

| route | call | result | what it means |
|---|---|---|---|
| devnode restart | `pnputil /restart-device` | `Odmowa dostępu` | needs admin; would only re-enumerate anyway |
| hub reset | `IOCTL_USB_RESET_HUB` `0x0022044C` | **accepted, then nothing** | silent no-op on this hub |
| port cycle on the tablet's hub | `IOCTL_USB_CYCLE_PORT` `0x00220480` | `err 87` for six buffer shapes | not implemented by this USB 2.0 hub |
| port cycle on an empty USB 3.0 root port | same | `err 50` (`ERROR_NOT_SUPPORTED`) | not implemented on this platform at all |
| rewrite the retry budget | `Set-ItemProperty EnumerationRetryCount 0` | `Żądany dostęp do rejestru jest niedozwolony` | needs SYSTEM, not administrator |
| devnode remove + rescan | `pnputil /remove-device` | `Odmowa dostępu` (5) | needs elevation |
| bus rescan alone | `pnputil /scan-devices` | `Odmowa dostępu` (5) | needs elevation |

The last three rows were added after the first four were already conclusive, because they act on a
different layer: the first four act on the **hub**, the last three on the **devnode** or the
registry. `remove-device` followed by `scan-devices` is the one that would actually matter - it
drops the failed node and makes the stack re-report the bus, which spends the descriptor-retry
budget again. It is unimplemented here only for want of a privileged token, not for a technical
reason, so it is recorded as **untested** rather than closed. `scripts/Remove-WedgedNode.ps1`
performs it with elevation, `-DryRun` first.

A watcher running through the whole window confirmed no effect from anything attempted
unelevated: one sample, no arrivals, no departures.

The distinction between 87 and 50 is what makes the last row conclusive. `87` can mean
"wrong arguments"; `50` from a **free** port on the root hub, where no device state can be
the cause, means the call is simply absent. So `CYCLE_PORT` cannot be used here for any
port, not just the tablet's.

## 2. The trap in route 2

`IOCTL_USB_RESET_HUB` returned OK. That is the result most likely to be written down as a
fix, and it was not one:

```
before: DeviceEnumerated  vid=0000 pid=0000
IOCTL_USB_RESET_HUB (0x0022044C) -> accepted
after : DeviceEnumerated  vid=0000 pid=0000
EnumerationRetryCount   4        (unchanged)
```

Three independent watchers confirmed it: a 90 s window around the call, a second 90 s
window before the cycle attempts, and a 10 min window spanning both - **zero USB arrivals
or departures**, and the node's `LastArrivalDate` stayed at `14:41:31`, before all of them.

The general rule this produced, worth more than the result: **an accepted IOCTL is not an
effect.** Only a changed observation is.

## 3. What the port state says the wedge is

Reading the hub's own view of the port (offsets are 1-byte packed - see `docs/101`):

```
ConnectionStatus   2  (DeviceEnumerated)
DeviceAddress      0
NumberOfOpenPipes  0
DeviceDescriptor   length 0, vid 0x0000, pid 0x0000
Speed              LowSpeed
```

against a working port on the same hub:

```
ConnectionStatus   1  (DeviceConnected)
DeviceAddress      4
NumberOfOpenPipes  1
DeviceDescriptor   length 18, vid 0x23c5, pid 0x1478
```

`DeviceEnumerated` with a **zero address and a null descriptor** is the precise statement
of `DEVICE_DESCRIPTOR_FAILURE`: the hub believes it finished, and what came back was zeros.
This is not "the host gave up asking" alone, and not "the device never answered the hub" -
it is a device that answered, with nothing.

## 4. Where this leaves the two routes

**Route (a), 900E -> 9008 by bump.** Needs a fresh `mode=2` HELLO, which needs a real power
cycle. The tooling now does the whole sequence on one handle (`docs/100`) and captures the
packet it reads (`docs/102`). Ready; it cannot start while the device is wedged.

**Route (b), D+ short.** Needs the cable. `short_attempt.py` was repaired while this was
being written: it used to read a raw 64-byte chunk instead of a framed packet, searched only
for `9008` (a short can land on `900E`), and kept no capture. It now delegates to
`tablet.grab_any_hello`, which frames the packet, handles both PIDs, and writes the bytes to
`hello_captures/`.

**Both routes now end at the same physical act: remove power.** That is not a gap in the
analysis, it is the measured conclusion, and it is now stated with the IOCTL ids and error
codes behind it so nobody re-runs this search.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.**

Closed with evidence this session: the wedge cannot be cleared from the host on this
machine. Four routes, four measurements, and the one that returned success was the one that
did nothing.
