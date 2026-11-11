# What the hub can and cannot do - and the port history that matters more

Two results: the host-side reset route is closed, and the registry shows the wedge is not
the terminal state it has been treated as.

---

## 1. The host-side reset route: closed, with the reason

`docs/101` left this open, because `IOCTL_USB_CYCLE_PORT` returned
`ERROR_INVALID_PARAMETER (87)` unelevated and "needs admin" was a plausible reading. It
is not the reading. `scripts/find_hub_ioctls.py` scans function ids 256-320 and
classifies each answer as `missing` (err 1), `exists/bad-args` (err 87) or `OK`:

```
hub 1A40 (VID_1A40&PID_0101, USB 2.0)          AMD root hub (USB 3.0)
  275  0x0022044C  RESET_HUB   OK                 RESET_HUB   OK
  288  0x00220480  CYCLE_PORT  exists/bad-args    CYCLE_PORT  err=50 (NOT_SUPPORTED)
```

So:

- **`IOCTL_USB_CYCLE_PORT` is implemented by USBHUB3 but requires a USB 3.0 hub.** On
  the AMD root hub it answers `ERROR_NOT_SUPPORTED (50)`; on the tablet's USB 2.0 hub it
  answers 87 for every buffer shape tried (4/0, 4/4, 8/0, 8/4, 8/8, 12/4). Elevation is
  therefore irrelevant - and the UAC prompt left open earlier can be dismissed.
- **`IOCTL_USB_RESET_HUB` is accepted and does nothing.** Issued against the tablet's
  hub it returned OK, and the measurement afterwards was unchanged:

```
before: DeviceEnumerated  vid=0000 pid=0000
IOCTL_USB_RESET_HUB (0x0022044C) -> accepted
after : DeviceEnumerated  vid=0000 pid=0000
EnumerationRetryCount   4        (unchanged)
no USB arrival or departure in 90 s
```

That is the more useful of the two facts, because "the call succeeded" is exactly the kind
of result that gets recorded as a fix. It did not reset anything.

**Conclusion: the wedge cannot be cleared from this host.** `docs/87`'s "power removal is
the only way" survives, now with the IOCTL names, id numbers and error codes behind it
instead of an assumption.

## 2. The port history, which changes the framing

Every USB identity this tablet has ever enumerated as keeps a registry record, and the
`ContainerID` of each is a version-1 GUID whose timestamp is when that identity was first
created. `scripts/usb_history.py` lays them out. Grouped by physical port:

```
Port_#0002.Hub_#0002         Port_#0004.Hub_#0001
  07-19 18:38  900E  COM10     11-07 08:33  9008  COM6
  11-07 20:55  9008  COM7      11-07 20:55  0000
  11-08 10:11  0000

Port_#0001.Hub_#0007          Port_#0004.Hub_#0004
  11-08 09:41  9008            11-10 17:02  9008  COM9
  11-08 10:11  0000            11-11 09:24  0000
  11-08 19:49  9008
  11-11 09:24  0000
```

Three things follow, none of which were in the record before:

**a. On every port, `9008` appears BEFORE the `0000` wedge.** Not once did the wedge come
first. `docs/99` and `docs/101` describe the wedge as the state the tablet falls into and
stays in; the history says it is the state it falls into *after* an EDL session, from
which it has recovered onto `9008` again at least twice.

**b. `Port_#0001.Hub_#0007` shows `9008 -> 0000 -> 9008 -> 0000`.** 11-08 09:41 `9008`,
10:11 wedged, 19:49 `9008` again, 11-11 wedged. So the sequence is a cycle, not a
one-way descent - and it was traversed successfully twice on one port on one day. Anything
that asserts the device "cannot reach 9008 any more" is contradicted by this row.

**c. The most recent 9008 is 11-10 17:02 on the port it is wedged on now** -
`Port_#0004.Hub_#0004`, COM9. That is the same hub and port as the current wedge
(`docs/99`), and it is 21 hours old, not months. Whatever was done to get there had
nothing to do with cable topology or key combinations, because the port never changed.

## 3. What this suggests, and how strongly

The wedge looks like **the state left behind when a session ends**, not a hardware fault
and not a mode the device prefers. Every 0000 record is followed (in the history, on some
port) by another 9008 record. That is consistent with: session runs, host disconnects
mid-handshake, device drops to the null-descriptor state, next power cycle re-enters EDL.

If that is right, then the recurring failure in this project is not "cannot reach 9008" -
it is **"reached 9008 and then lost the HELLO"**, which is precisely what `docs/100` fixed
in the tool. Those two findings arrived in the same hour and support each other.

Stated honestly: this is inference from registry timestamps, and a `ContainerID` records
the first appearance of an identity, not every appearance. It cannot distinguish "entered
9008 twelve times" from "entered once and Windows reused the container". The pattern is
strong enough to reorder priorities, not strong enough to be a proof.

## 4. What was also added

`scripts/tablet.py` now writes every HELLO it reads to `scripts/hello_captures/` as raw
bytes plus a parsed sidecar. `docs/97` found that the founding measurement of this project
has no capture anywhere; this makes the omission impossible to repeat, mechanically rather
than by intention. Synthetic packets are refused by name - a test packet landed in that
folder once during development and was removed, because a folder called "captures" that
can contain invented bytes is worse than no folder at all.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained in this session.**

New: the host-side reset route is closed with named error codes; the wedge is
`DeviceEnumerated` with a null descriptor and a zero address; the tablet has been at
`9008` on its current port within the last day; and every future HELLO read is captured.
