# Vol+ again gives the wedge - and the registry shows this exact port produced 9008 before

Two findings from one attempt, one of them a correction to docs/94-98.

---

## 1. The attempt, measured

Procedure: unplug, Power held ~20 s, plug in with **Volume Up held**, watcher running on every
USB node with no VID filter.

```
14:35:06   node arrival (previous plug)
14:36:11   - LEFT     USB\VID_0000&PID_0002\9&1FF60AC4&0&4      (cable out)
14:36:24   + ARRIVED  USB\VID_0000&PID_0002\9&1FF60AC4&0&4      (13 s later)
```

One arrival, one departure, nothing else on the bus. The device came back with:

```
instance   USB\VID_0000&PID_0002\9&1FF60AC4&0&4
parent     USB\VID_1A40&PID_0101\8&1B878445&0&4
location   Port_#0004.Hub_#0004
address    4
status     Error, Code 43, HWID USB\DEVICE_DESCRIPTOR_FAILURE
COM ports  COM1 only
```

**Volume Up + cable does not reach 9008.** It reaches the same `DEVICE_DESCRIPTOR_FAILURE`
that docs/85 recorded, now twice for twice. Vol+ is 0 for 2.

## 2. What the failure code actually says

New: the node's `Device Parameters` key carries the USB stack's own accounting.

```
EnumerationRetryCount  : 4
EnumerationFailureCode : 1073807360  (0x40010000)
```

Read that together: **Windows asked for the device descriptor four times and then stopped.**
The node is not a device that keeps failing - it is a host that gave up after the retry budget.
That is why it sits still indefinitely: nothing is being retried any more. It also means the
`STATIC` verdict from `scripts\watch_unknown.py` was correct but for a reason worth naming -
a static node is *Windows declining to ask again*, not the boot ROM refusing.

All five `VID_0000&PID_0002` records on this machine carry the identical `4 / 0x40010000`,
including the two older ones behind different hubs. Same ceiling, same give-up.

## 3. The correction: this port has already delivered 9008

docs/94, docs/96 and docs/98 built a case that the hub is what wedges the tablet, from two
observations four minutes apart (13:24 direct port = `900E`; 13:28 hub = wedged). docs/98 §3
stated the sample size was one and named the test that would settle it.

The registry settles it without the test. Enumeration history survives there per instance id,
and the instance id encodes the port:

```
HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_05C6&PID_9008\9&1ff60ac4&0&4
    DeviceDesc  Qualcomm HS-USB QDLoader 9008
    Location    Port_#0004.Hub_#0004          <- identical to the node wedged right now
    Driver      oem61.inf (qcwdfserial)
    PortName    COM9
    Container   {7bfd5dd5-dd28-11f1-bdd0-f8ac65ed7131}   created 2026-11-10 17:02:17
```

`9&1ff60ac4&0` is the `ParentIdPrefix` of hub `8&1B878445&0&4`. So this is **the same hub and
the same port** the tablet is wedged on now - and on it, this device has enumerated as
`QDLoader 9008` and been given **COM9**, the port docs/25 used for the QSaharaServer upload
that completed "1 554 996 bytes, Sahara protocol completed".

The same hub has a second such record on another port:

```
VID_05C6&PID_9008\8&1b878445&0&2   Port_#0002.Hub_#0002   COM7   created 2026-11-07 20:55
```

**Two 9008 enumerations through a `VID_1A40` hub.** The hub is not the blocker. The 13:24 /
13:28 correlation in docs/98 was the replug mechanism from docs/07 §D3, not topology.

Why this matters: docs/97 recorded that most negative results in this project were taken
through hubs and were therefore suspect. For the *tablet* specifically that suspicion is now
retired - hubs are fine. What is fragile is the moment of insertion, not the path.

## 4. Where that leaves the entries

| entry method | attempts | outcome |
|---|---|---|
| Vol+ held at insertion | 2 | wedged `VID_0000&PID_0002`, both times |
| Vol+ and Vol- together | 1 | wedged `VID_0000&PID_0002` |
| no keys, direct port | 1 | `900E`, COM10, HELLO already spent |
| no keys, through hub | ? | `9008` + COM9 recorded on this port twice |

The pattern that survives every attempt is the opposite of what was being tried: **holding a
volume key at insertion is exactly what produces the descriptor failure.** The clean entries
this device has ever had were the ones with no key held.

That also fits docs/77: the firmware itself toggles D+ for ~200 ms during boot. A key held at
insertion changes the electrical state during that window. Vol+ has no driver in XBL at all
(docs/47 - it is a PM8550 gpio6 key), so it cannot be selecting a mode; it can only be
interfering with the handshake.

## 5. Next action

1. unplug
2. hold Power 20-30 s, until the screen is dark
3. plug in **holding nothing**
4. `python scripts\tablet.py wait --want 900e --seconds 90`

Vol+ is done. It has produced the wedge twice and 9008 zero times, and there is no mechanism
in the boot ROM by which it could do anything else.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.**

New in this document: the wedge is the host abandoning a 4-retry budget, and the hub theory is
retired by the registry - this port has produced `9008`/COM9 before, which makes the topology
section of docs/94/96/98 obsolete and re-opens every hub-based result as possibly valid.
