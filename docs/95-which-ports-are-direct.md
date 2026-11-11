# Which ports on this host are direct, and which are hubs

Mapped 2026-11-11 13:19. `docs\94` made "plug into a rear port with no hub" step 0 of the short
procedure. This is the evidence for which ports those are on this machine, so the step can be
followed rather than guessed.

---

## 1. Root hubs present

Three USB 3.0 root hubs (AMD xHCI):

```
USB\ROOT_HUB30\7&14c6e8ad&0&0
USB\ROOT_HUB30\7&30304c2c&0&0
USB\ROOT_HUB30\5&2c35141&0&0
```

## 2. Devices that are directly attached (parent = a root hub)

```
VID_0B05&PID_18F3   composite        parent USB\ROOT_HUB30\7&14c6e8ad&0&0
VID_3299&PID_0012   composite        parent USB\ROOT_HUB30\7&30304c2c&0&0
VID_1A40&PID_0101   hub              parent USB\ROOT_HUB30\7&14c6e8ad&0&0
VID_1038&PID_183C   composite        parent USB\ROOT_HUB30\5&2c35141&0&0
VID_1A40&PID_0101   hub              parent USB\ROOT_HUB30\7&30304c2c&0&0
```

**Two generic hubs (`VID_1A40`) are plugged directly into the machine.** Everything else on
this host is downstream of one of them - including the tablet, in both of its recent positions
(`docs\91`, `docs\94`).

## 3. What that means concretely

The tablet's parent was `VID_1A40` first and `VID_0A05` second. The second is itself
downstream of a `VID_1A40`, so the recent chain was:

```
root hub -> VID_1A40 hub -> VID_0A05 hub -> tablet
```

**Two hubs deep.** That is further from the machine than at any earlier point in this project,
and it is the opposite of what `docs\81` recommends for an EDL attempt.

## 4. The instruction, made specific

A port is direct if the device attached to it shows a parent of the form
`USB\ROOT_HUB30\...`. On this machine that means:

- **unplug one of the two `VID_1A40` hubs and use that socket** - it is a direct port, already
  proven to host a device;
- or use any other socket on the machine's rear I/O panel that is not currently feeding a hub;
- **do not** use a port on a monitor, dock, keyboard, USB strip or the front panel if those
  were the ones feeding the hubs.

Verification after plugging in, without unplugging anything:

```powershell
Get-PnpDeviceProperty -InstanceId "USB\VID_0000&PID_0002\<serial>" -KeyName DEVPKEY_Device_Parent
```

The answer must read `USB\ROOT_HUB30\...`. If it reads `USB\VID_xxxx&PID_xxxx`, the tablet is
still behind a hub and the attempt's step 0 has not been met.

## 5. Why this is worth a document of its own

Because it is the third time the same instruction has been given and not yet satisfied, and
each time the evidence was "the parent is a hub" - but the *specific* sockets that would work
were never named. They are named now.

It also corrects a misconception that has been implicit: **on this machine the rear panel is
not automatically direct.** Two hubs are plugged into the rear panel. The only reliable test is
the parent's instance id, not the physical location.

## 6. State

`HELLO ver=3 mode=0`: **not obtained.** Tablet wedged at
`USB\VID_0000&PID_0002\B&1D65D22F&0&1`, two hubs deep, `DEVICE_DESCRIPTOR_FAILURE`, no COM port.

It still needs power removed before anything else, and the next attempt should start from a
direct port - which is now specified.
