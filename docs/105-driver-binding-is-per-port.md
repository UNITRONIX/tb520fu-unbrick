# The driver binding is per PORT, and only 2 of 11 tablet sockets can be read

A finding that would have silently invalidated the next physical attempt, found by asking
a question the tooling had never asked: *will the COM port I am waiting for actually exist
on the socket the cable is in?*

---

## 1. The measurement

The enum record stores the driver **per instance id**, and a USB instance id encodes the
hub and its port. So the binding is per socket, not per device and not per build.
Measured on this machine (`scripts/driver_check.py`):

```
instance                             location              driver                    COM    readable?
VID_05C6&PID_9008\9&1ff60ac4&0&4     Port_#0004.Hub_#0004  Ports / qcwdfser          COM9   YES
VID_05C6&PID_900E\b6f2de0a           Port_#0002.Hub_#0002  Ports / qcwdfser          COM10  YES
VID_05C6&PID_9008\8&1b878445&0&2     Port_#0002.Hub_#0002  USBDevice / libwdi WinUSB COM7   NO
VID_05C6&PID_9008\8&384b90af&0&4     Port_#0004.Hub_#0001  USBDevice / libwdi WinUSB COM6   NO
VID_05C6&PID_9008\b&10baf955&0&1     Port_#0001.Hub_#0007  USBDevice / libwdi WinUSB        NO
VID_05C6&PID_9008\b&1d65d22f&0&1     Port_#0001.Hub_#0007  USBDevice / libwdi WinUSB        NO
```

**2 of 11 usable.** The `9008` identity on this very port (`Port_#0004.Hub_#0004`) is bound
to `qcwdfser` and carried COM9 when the tablet was last there on 11-10 at 17:02. Two other
`9008` sockets are bound to libwdi's WinUSB package, which exposes no serial port at all.

Note also the two `9008` rows that record a `PortName` (COM7, COM6) while the driver is
WinUSB. Those COM numbers are **stale leftovers from an earlier binding** - a `PortName`
value in the registry proves a port once existed, not that it will exist again. Reading it
as current is how a dead socket looks alive.

## 2. Why this matters more than it looks

The failure it produces is indistinguishable from the failure this project has been chasing
for days. If the cable is in a libwdi-bound socket:

1. the tablet reaches `9008` - the enumeration succeeds, the PID is right;
2. `tablet.py catch` waits for a Qualcomm COM port that never appears;
3. the run reports "no port" and the ledger records a failed attempt;
4. the obvious next conclusion is "the HELLO was spent again, power-cycle it".

Step 4 is wrong, and each iteration of it costs a physical power cycle plus a plausible but
false entry in the record. The actual fix is one command, and it does not need the tablet
present - the binding is visible in the registry whether the device is plugged in or not.

## 3. Where it leaves the current plan

The tablet is wedged on `Port_#0004.Hub_#0004` - **the socket whose `9008` identity is bound
to `qcwdfser`**. That is the good socket. If it comes back as `9008` there, a COM port will
appear and the HELLO is readable.

Two sockets are on the same hub as the tablet (`8&1b878445`): port 4 (the tablet) and port 1
(a `0A05` hub downstream, whose `9008` identity is not recorded here at all). So the cable
should not be moved; the socket it is in is the right one.

## 4. A bug in the check itself, worth recording

The first version of `driver_check.py` compared the class GUID in lowercase against a
registry that writes it in lowercase, and still reported **every** row as unusable -
including the two genuine `qcwdfser` ones. The cause was comparing a raw string containing
an uppercase `D` in `{4D36E978-...}` against a lowercase constant. Fixed by upper-casing
both sides.

The reason this belongs in the document: a check that always answers NO is worse than no
check. It would have sent the next attempt to "fix the driver" on a socket that was already
fine, and the real problem - the socket that is genuinely WinUSB-bound - would have stayed
invisible.

## 5. Status

`HELLO ver=3 mode=0`: **not obtained.**

New: the read-side precondition is now checkable before the cable goes in, and the socket
the tablet is on is one of the two that can actually be read.
