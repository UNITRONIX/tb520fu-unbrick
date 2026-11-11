# The COM world works: the programmer upload succeeded

This document records the first time Lenovo's own toolchain was actually run against
this tablet in its correct driver world — and what it proved.

---

## 1. The driver switch succeeded

`Switch-QualcommDriver.ps1` staged `qcwdfser.inf` as `oem61.inf` and restarted the
node. Result:

```
Before:  USB\VID_05C6&PID_9008  service=WinUSB      inf=oem67.inf
After:   USB\VID_05C6&PID_9008  service=qcwdfserial inf=oem61.inf
```

and a real COM port appeared:

```
Qualcomm HS-USB QDLoader 9008 (COM9)    Class=Ports    Status=OK    Problem=NONE
```

So the earlier conclusion that no Qualcomm serial driver was available for these PIDs
was wrong for this machine. The package in
`C:\Program Files\Qualcomm\Qualcomm USB Drivers\drivers\qcwdfser.inf` covers `9008`
and `900E`, and binding it produces a working port.

## 2. QSaharaServer completed a full transfer

```
QSaharaServer.exe -p \\.\COM9 -s 13:.\image\xbl_s_devprg_ns.melf

10:42:50: Requested ID 13, file: "...\xbl_s_devprg_ns.melf"
10:42:50: 1554996 bytes transferred in 0.156000 seconds (9.5062MBps)
10:42:50: File transferred successfully
10:42:50: Sahara protocol completed
```

**1 554 996 bytes at 9.5 MB/s, "Sahara protocol completed".**

That number — 1 554 996 — is exactly what every raw-libusb session measured, and it is
the sum of the image ranges the device requests. So this is the same successful upload
the project has been performing all along, now confirmed by the vendor's own tool.

What is new is not that the transfer works. It is that **the vendor's tool agrees the
Sahara stage completed normally**. Any theory that the upload itself is defective is
now closed by an independent implementation.

## 3. What happened next is the important part

Immediately after the transfer:

```
COM9:      gone
9008 node: gone entirely
Device list: no VID_05C6 device of any kind
```

The device vanished from USB **within the same second** as the transfer completing.

That is different from every previous observation, where the disappearance came
**~8 seconds later** and was followed by a watchdog reset. Here it was immediate.

Two readings, and the data does not yet choose between them:

- the programmer started, failed hard, and the SoC reset at once rather than hanging
  until the watchdog;
- the serial driver's close path after `QSaharaServer` exited disturbed the device.

The second is plausible and untested: `fh_loader` was run immediately afterwards and
reported `Failed to open com port '\\.\COM9'` — because the port no longer existed at
that moment. That error therefore says nothing about `fh_loader` or about Firehose.

## 4. Why this matters

**The COM world is now proven to work.** That was the open question in
`24-lenovo-tools-com-world.md`, and the answer is yes: the driver binds, the port
appears, and the vendor tool talks to the device.

The remaining question is narrower and different from before:

> After `Sahara protocol completed`, does the programmer raise a Firehose endpoint
> quickly enough for `fh_loader` to reach it on the same port?

`Rescue.cmd` runs `QSaharaServer` and then `fh_loader` as two separate processes, both
opening `\\.\portname`. That is Lenovo's own design, so it is expected to work on a
healthy device. On this unit the port disappeared between the two.

## 5. The next attempt, and why it differs

### Update after the power cycle: the COM world survives, and 900E has its own port

After a power cycle the tablet returned as `900E` with the serial driver **still bound**:

```
USB\VID_05C6&PID_900E  service=qcwdfserial  inf=oem61.inf
Qualcomm HS-USB Diagnostics 900E (COM10)
```

So the driver switch persists, and — this is the useful part — **crashdump mode gets its
own COM port too** (`COM10`, "Diagnostics 900E"). The earlier assumption that only
`9008` exposes a port was wrong.

`QSaharaServer` then talked to `900E` over COM10 and received a genuine HELLO:

```
10:44:30: STATE <-- SAHARA_WAIT_HELLO
10:44:30: Received 8 bytes
10:44:30: First few bytes: 01 00 00 00 30 00 00 00
10:44:30: Header indicates command 1 and packet length 48
```

`01` is `HELLO_REQ`, `0x30` is the 48-byte packet length. **That is the vendor tool
correctly decoding this device's Sahara handshake over a COM port** — something that had
never happened in this project.

### And then the same constraint appeared

The immediately following run read `FF FF FF FF FF FF FF FF` and reported:

```
Header indicates command -1 and packet length -1 bytes
ERROR: Command packet length -1 too large to fit
ERROR: Sahara protocol error
```

`FF FF FF FF` is an empty read. The HELLO had already been consumed by the previous
invocation. **This is the one-HELLO-per-reset constraint**, now demonstrated against the
vendor tool as well as against the custom code: it is a property of the device, not of
the tooling.

That is a genuinely useful confirmation. It means every attempt must be a **single
first contact** after a fresh cycle.

### The revised procedure

```
1. power cycle
2. immediately: QSaharaServer on the 900E COM port with the programmer
   (or bump with the raw tooling first, then QSaharaServer on the 9008 port)
3. fh_loader immediately after, same port, nothing in between
```

The order matters more than anything else measured tonight. One probe, one attempt.

---

## 6. What not to conclude

- **Not** "the COM path fails like the others". The upload succeeded, by the vendor's
  own accounting. Only the handover to `fh_loader` is unresolved.
- **Not** "the driver switch broke the device". The device disappeared at the end of a
  successful transfer, which is what a programmer taking over and then failing looks
  like.
- **Not** "`fh_loader` cannot open the port". It could not open a port that had already
  ceased to exist. That is a different statement.

## 7. A correction worth recording

Earlier in the project, `07-dead-ends.md` §A2 recorded this path as a dead end on the
strength of the same `Failed to open com port` message. That conclusion was reached
without noticing that the Sahara stage had completed successfully, and without checking
whether the port still existed at the time. Both are now checked, and both matter:
the port had already gone.

That is the third time in this project that an error message was read as a verdict about
the device when it was a statement about timing or about the tool's own environment.
