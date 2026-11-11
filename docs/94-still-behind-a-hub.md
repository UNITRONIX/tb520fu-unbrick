# Still behind a hub: the port changed, the topology did not

Checked 2026-11-11 13:19. The node moved, but not to where it needs to be.

---

## 1. What changed

```
before   USB\VID_0000&PID_0002\9&1FF60AC4&0&4    Parent = hub VID_1A40&PID_0101
now      USB\VID_0000&PID_0002\B&1D65D22F&0&1    Parent = hub VID_0A05&PID_7211
                                                  Location = Port_#0001.Hub_#0007
```

The device was moved to a **different** hub. The parent is still a generic USB 2.0 hub
(`VID_0A05` this time, `VID_1A40` before), not a root port.

Hardware id is unchanged: `USB\DEVICE_DESCRIPTOR_FAILURE`, problem 43.

## 2. Why this matters

`docs\91` identified the hub as a variable that was never controlled in this project, and
`docs\93` §4 put "plug directly into a rear USB 2.0 port" as step 1 of the short procedure,
because the field sources recommend a direct connection precisely to avoid hub behaviour.

**A different hub is not the same as no hub.** Two hubs of the same class can share whatever
property is causing trouble - and in this case the failure signature did not change at all,
which is itself informative: the wedge followed the device to the new hub.

That leans toward the wedge being the device's own state (`docs\07` §D3: PBL wedged
mid-negotiation) rather than something the first hub introduced. But it does not rule the hub
out as a *contributing* factor when the device is healthy enough to negotiate.

## 3. What to check on the host

A root port can be identified without unplugging anything:

```powershell
Get-PnpDevice -PresentOnly -Class USB |
  Where-Object { $_.FriendlyName -match 'koncentrator|hub' } |
  ForEach-Object {
    $p = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Parent
    "{0}  parent={1}" -f $_.InstanceId, $p.Data
  }
```

A device attached directly to the machine shows a parent whose instance id **ends in the root
hub pattern** (e.g. `USB\ROOT_HUB30\...`), not `VID_xxxx&PID_xxxx`.

Simpler: look at the physical machine. **Rear I/O ports are usually direct. Front-panel ports
and any port on a monitor, dock, keyboard or USB strip is a hub.** The tablet must go into a
rear port for the next attempt.

## 4. State of the device

```
USB\VID_0000&PID_0002\B&1D65D22F&0&1   Error, Code 43, DEVICE_DESCRIPTOR_FAILURE
no VID_05C6 node, no COM port
```

Unchanged in substance: the tablet is on the bus and cannot deliver a descriptor. It needs
power removed before anything else.

## 5. The attempt sequence, restated with the topology fixed

```
0. tablet into a REAR port, no hub in the chain   <- the one thing still wrong
1. unplug, hold Power 20-30 s until dark
2. twist D+ (green) and GND (black), hold
3. plug into the tablet, orientation A
4. plug the A end into the PC
5. hold 5 s, release
6. python scripts/short_attempt.py --summary     (after recording with --orientation A)
7. flip the plug, repeat as orientation B
```

Step 0 has now been attempted twice and has not yet been done. That is the next thing to
change, and it costs nothing.
