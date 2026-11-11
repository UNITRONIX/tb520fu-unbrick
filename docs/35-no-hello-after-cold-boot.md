# The 900E node no longer emits a HELLO at all

This is the result of the most careful attempt of the session, and it is a
negative that has to be recorded rather than worked around.

---

    10|## 1. The experiment, stated exactly

Everything the earlier failures could be blamed on was eliminated:

| possible cause of previous failures | how it was removed |
|---|---|
| the port was opened too late | one handle held from before the reset |
| opening and closing discarded the buffer | the handle is never closed in the normal path |
| our `SAHARA_RESET` was cycling the device | no reset is sent, ever, in this tool |
| a "ghost" node was being opened | the handle is the same one held across the cycle |
| the re-enumeration was missed | reopen begins the moment the old handle dies |

`scripts/hold_and_catch.py`, one run, verbatim:

```
[  0.011]   handle open (death #0)
[  0.011]   HOLDING the handle. RESET THE TABLET NOW
[ 13.717]   handle died (SerialException) - device re-enumerated
[ 30.173]   handle open (death #1)
...then nothing, for the remainder of a 180 s budget
```

Between `13.717` and `30.173` the tablet was off the bus for 16.5 s - the power
cycle really happened. The handle came back on the new node at 30.173 s and read
for over 100 seconds.

**Zero bytes.**

## 2. What that means

The tablet reaches `900E`, enumerates as a Qualcomm diagnostics port, and stays
there - but emits no Sahara packet. The port is open and alive (no error, no
disconnect); it is simply silent.

Compare with `docs/25-com-world-works.md` and the vendor log of 2026-11-11
11:02:06, where the same port delivered a complete `HELLO_REQ`:

```
First few bytes: 01 00 00 00 30 00 00 00
```

So the capability existed on this unit earlier today. It does not exist now.

## 3. The two readings, and which is better supported

**a) The firmware is no longer reaching Sahara init.**
Something in the boot path changed, so the crash-dump handler comes up and
enumerates USB, but the Sahara server inside it never starts. That is consistent
with the device having been reset many times today, and with `RST_STAT = 0x3`
(watchdog, `docs/15` §5) - a device whose boot is being collected by the watchdog
at a point before Sahara is reached would show exactly this: the node appears,
and nothing is sent.

**b) The packet is consumed before our handle is live.**
The reopen at 30.173 s might still be after the emit. This is the one gap left,
and it is testable only by opening the port *earlier* than the node appears -
which the CDC driver does not permit, because the device node is what creates the
port.

Reading (a) is more likely: the port was held continuously for over 100 s after
reopening and never produced anything, and a packet emitted "just before" the
open would still be sitting in the driver's receive buffer, which is precisely
the buffer we are reading.

## 4. What this closes, and what it does not

Closed:

- "we were opening too late" - no, the handle was held.
- "closing the port discarded it" - no, the handle was never closed.
- "our own reset was cycling the device" - no reset was sent.
- "a ghost node was being read" - the same handle survived the cycle.

Not closed:

- whether a **fully clean** power cycle (battery disconnected, or the device left
  off for minutes) restores Sahara init. Every cycle today was a key-hold reset,
  and the device may need longer than that to clear the state that precedes the
  crash dump.
- whether the write gate could be reached another way. `docs/17-write-gate.md`
  still stands: the lock is a byte, and it fails open. But it needs a running
  programmer to consult it.

## 5. Practical advice for the next attempt

Do not repeat today's loop. It produced four negative results and no data:

1. a key-hold reset is not enough to get a HELLO back;
2. `SAHARA_RESET` never produces one, and it destroys the port;
3. closing and reopening the port is not what loses the packet - the packet is
   not being sent;
4. therefore no amount of client-side timing work will recover it.

The next thing to try is a **discharge**, not a reset: leave the tablet off and
unplugged long enough for the PMIC to lose residual state (the "hold Power ~15 s"
reset leaves RTC domain and some always-on blocks alive). If the node comes back
after that and still says nothing, the Sahara stage of this device is gone and the
remaining routes are the ones `docs/18-escalation-surfaces.md` ranks, all of which
need the case opened.
