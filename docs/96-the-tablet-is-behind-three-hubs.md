# The tablet is behind three hubs — and only it is on that branch

Checked 2026-11-11 13:19, after the owner said the hub has no other cables and can be
disconnected entirely.

---

## 1. The chain, traced through the parents

```
tablet              USB\VID_0000&PID_0002\B&1D65D22F&0&1
  parent ->         USB\VID_0A05&PID_7211\A&91898CB&0&1      hub
    parent ->       USB\VID_0A05&PID_7211\9&1FF60AC4&0&1      hub
      parent ->     USB\VID_1A40&PID_0101\8&1B878445&0&4      hub
        parent ->   USB\ROOT_HUB30\7&14c6e8ad&0&0             root port
```

**Three hubs in series.** At no point in this project has the tablet been further from the
machine, and it is the opposite of the configuration the field sources recommend for an EDL
attempt (`docs\81`): a direct connection to a USB 2.0 port.

## 2. Nothing else is on that branch

Devices whose parent is `VID_0A05&PID_7211\A&91898CB&0&1`:

```
tablet   (Error, Code 43)
```

**That is the entire list.** The two `VID_0A05` nodes are the hub itself at two addresses, and
the only thing downstream is the tablet. So removing that hub removes nothing but the tablet's
own path - which is exactly what is wanted.

`VID_1A40\8&1B878445&0&4` has one other device on it (a composite device), but that one is one
level higher and is not in the way.

## 3. So the physical step is now unambiguous

```
1. unplug the VID_0A05 hub from the VID_1A40 hub
2. plug the tablet's cable directly into a socket on the VID_1A40 hub
   - or, better, into a socket that reports USB\ROOT_HUB30 as the parent
3. verify before anything else:
     Get-PnpDeviceProperty -InstanceId <tablet> -KeyName DEVPKEY_Device_Parent
   must read USB\ROOT_HUB30\...  (one hub is acceptable, three is not)
```

**One hub is tolerable.** Three is not: each hub re-drives USB 2.0 signalling, adds its own
descriptor handling, and can hold a device in a failed state of its own. For a device that
cannot deliver a descriptor, that is three places for the failure to happen instead of one.

## 4. What this does not fix

Removing the hubs will not clear the current wedge. `docs\07` §D3's explanation - PBL stuck
mid-negotiation - is about the device, and the state followed it across two different hubs
already (`docs\94`).

So the order is:

```
1. simplify the topology      (this document)
2. power the tablet down 20-30 s
3. attempt the short, orientation A, then B (docs/93, scripts/short_attempt.py)
```

Step 1 matters because it removes three uncontrolled variables from the attempt, and costs one
cable move.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.** Tablet wedged, three hubs deep, no COM port.

The topology is now fully mapped and the change is a single cable move. Nothing else in this
project depends on the hubs being there.
