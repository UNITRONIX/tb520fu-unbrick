# The hub port can be read from the host - and maybe cycled, with elevation

A new measurement surface, found while looking for a way to un-wedge the tablet
without physical access to the cable.

---

## 1. Why this was attempted

`docs/87` and `docs/99` repeat one conclusion: the wedged node needs power removed, and
    10|"no host-side action changes that". The evidence for that was `pnputil
/restart-device`, which requires elevation and would only re-enumerate anyway.

But the registry says the stall is *host-side*:

```
EnumerationRetryCount  4
EnumerationFailureCode 0x40010000
```

Windows stopped asking. A hub-port cycle puts the port through disconnect/connect,
which makes the hub re-report the device and the stack spend its retry budget again.
That is a different action from restarting the devnode, and it was never tried because
the tooling to reach a hub port did not exist in this repository.

## 2. What is now measured, per port

`scripts/reset_port.py --info` opens each hub's device interface and issues
`IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX` for ports 1-8. The tablet's port:

```
target: USB\VID_0000&PID_0002\9&1FF60AC4&0&4
        -> USB\VID_1A40&PID_0101\8&1b878445&0&4 port 4
before: DeviceEnumerated  vid=0000 pid=0000
```

**`DeviceEnumerated` with `vid=0000 pid=0000`** is the cleanest description of this
failure obtained so far, and it corrects a reading in `docs/99`:

- the hub DID assign an address and reports the port as *enumerated* - so this is not a
  device that never got that far;
- but the descriptor it read back is all zeros, which is why `DEVICE_DESCRIPTOR_FAILURE`
  is the only hardware ID Windows can build.

So the failure is not "the device stopped answering" and not "Windows gave up before
addressing it". It is: **addressed, then handed back a null descriptor.** That is what
the boot ROM in its crashdump USB state looks like from the hub's side.

## 3. Two bugs this cost, both worth recording

**Wrong IOCTL ids.** The first version used `(0x22 << 16) | (fid << 2)` with `fid` from
18 upward, inferred from a remembered value of `IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX`
as `0x00220048`. The real ids come from `USB_CTL(id) = CTL_CODE(FILE_DEVICE_USB, id, ...)`
with `id` in the 258-290 range, so the actual values are `0x00220448`, `0x0022044C`,
`0x0022045C`, `0x00220480`. With the wrong number the call **succeeds** and returns
nothing, which reads exactly like "no device connected on any port" - and that is what
the first run reported, for every port on every hub.

**Wrong struct offsets.** The response is 1-byte packed, not naturally aligned. Reading
`ConnectionStatus` at offset 32 gives `0x07000000` for a healthy port. The proof of
packing is the pipe list: the first `USB_ENDPOINT_DESCRIPTOR` appears as
`07 05 81 03 01 00 ff` at offset **35**, so the fixed part is 35 bytes and
`ConnectionStatus` is at **31**. With the right offsets every port in the machine
reports something sensible: `vid=0a05 pid=7211`, `vid=1a40 pid=0101`, `vid=3299 pid=0012`.

Both failures produced confident, systematic, wrong output. Neither was caught by
reading the numbers - only by comparing a known port against what the device tree
already said it was.

## 4. The cycle itself: blocked on elevation, not on capability

```
IOCTL_USB_CYCLE_PORT (0x00220480) -> refused (err 87)
administrator: False
```

`ERROR_INVALID_PARAMETER` (87) from this IOCTL with several buffer shapes
(4-in/0-out, 8-in/0-out, 4-in/4-out) points at privileges, not at arguments: the call
needs an administrator token. `scripts/Cycle-TabletPort.ps1` re-launches the tool with
`RunAs` and routes output through `cmd /c ... > log` - PowerShell 5.1 refuses
`-Verb RunAs` together with `-RedirectStandardOutput`, which is its own small trap.

**Status: attempted, awaiting the UAC prompt.** No result yet at the time of writing.
The outcome decides between two useful things:

| if the cycle succeeds | if it is refused even elevated |
|---|---|
| the wedged state can be cleared from the host, and every future attempt stops depending on cable access | the port reset is unavailable on this hub, and physical replug remains the only way - now with the reason named |

## 5. What this does not change

`HELLO ver=3 mode=0` is still not obtained. Reading a hub port does not produce a HELLO,
and a port cycle at best restores the state the device was already in. The value here is
diagnostic and mechanical: one more way in, and a precise statement of what the wedge
actually is.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

New: the wedge is `DeviceEnumerated` with a null descriptor, readable per port from the
host; and the port-cycle route exists but needs administrator rights.
