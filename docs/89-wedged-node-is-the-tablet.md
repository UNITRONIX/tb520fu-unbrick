# The wedged node is confirmed to be the tablet, on the same port

A short verification, because "VID_0000&PID_0002" is not a vendor ID and could in
principle be anything.

## The check

The tablet's USB location while it was working, recorded in `docs/52`:

```
COM10  Qualcomm HS-USB Diagnostics 900E
       USB VID:PID=05C6:900E SER=B6F2DE0A LOCATION=1-4.4
```

The wedged node's location, queried from PnP just now:

```
USB\VID_0000&PID_0002\9&1FF60AC4&0&4
  DEVPKEY_Device_LocationInfo = Port_#0004.Hub_#0004
```

`Port_#0004.Hub_#0004` is the same physical port as `LOCATION=1-4.4` - root hub 1,
hub port 4, device port 4.

## What that establishes

The node that will not answer a descriptor request is **the tablet**, on the port it
has always used. It is not a stray device, not a different peripheral, and not a
Windows artefact from another hub.

That matters because every conclusion in `docs/87` and `docs/88` depends on the
wedged node being the tablet. It is.

## What it does not change

Nothing about the remedy: the device must lose power. But it removes the last
alternative explanation for the stuck state, and it costs one property query to keep.
