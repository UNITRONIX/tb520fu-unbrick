# The device stopped cycling

A behavioural change in the tablet, recorded because it invalidates assumptions the
earlier tooling was built on.

---

## 1. What was normal

Established by measurement earlier in the project (`05-firehose-and-the-silence.md`,
and again with `edl_coach.py watch`):

```
900E present  ~40-50 s
absent        ~12-15 s
900E present  ...
```

The device boot-loops. It appears as crashdump, is reset by the watchdog, disappears
while the bootloader runs without USB, and returns. Every capture tool written in this
project assumes that pattern: wait for absence, then for reappearance, then capture.

## 2. What is happening now

`timing_window.py` sampled node openability at ~7 Hz for 80 seconds:

```
absent               0 samples   (0.0%)
present-noopen     490 samples  (99.8%)   errno 13, Access denied
open-noREAD          1 sample   (0.2%)
READ                 0 samples   (0.0%)
```

**The node never left the bus for the whole 80 seconds.** The boot loop has stopped.
The device sits in a steady state where the node is enumerable but cannot be opened.

`probe_pattern.py` confirms the same thing from the Sahara side: six bare HELLO probes
two seconds apart, all failing, with no reset sent between them.

## 3. What it is not

`access_denied_diagnosis.py` rules out every host-side explanation:

```
Status       OK
Class        USBDevice
InstanceId   USB\VID_05C6&PID_900E\B6F2DE0A
service      WinUSB          <- correct driver for pyusb
problem      0               <- Windows considers the device healthy
serial ports COM1 only       <- no Qualcomm COM port appeared; not "world B"
EDL processes none           <- no orphan holding the handle
```

So:

- not a driver-world mix-up (`07-dead-ends.md` §A6);
- not an orphaned process holding the interface (§F1);
- not a PnP problem — Windows reports the node as working.

The refusal is coming from the device, not the host: it accepts the enumeration and
then does not participate.

## 4. Why this matters for the tooling

Every capture helper in this repository waits for an absence before treating a node as
fresh, on the assumption the device cycles. Against a device that does not cycle, that
logic either waits forever or gives up — which is exactly what several runs did, each
time looking like a separate failure.

This is the honest explanation for a sequence of confusing results tonight:

```
check_tablet      got a HELLO
reset_culprit     no HELLO, 3 s later, same node
probe_pattern     6 failures, 0 HELLO
timing_window     present but not openable, 80 s straight
session_hygiene   declared the node mute
```

Those are not five different problems. They are one device that stopped cycling and a
set of tools that assume it does.

## 5. What is and is not known about the cause

Not known: whether this state is a consequence of the many MEMORY_DEBUG sessions
opened and abandoned tonight, or something the device did on its own.

Worth noting against the first hypothesis: the session leak was real and was fixed
(`dec91f9`), and the wedge appeared before that fix. So the leak is a plausible
contributor, not a proven cause.

Also worth noting: a power cycle has restored the device twice tonight. It is the
remedy, and it is cheap.

## 6. What the next session should do differently

1. **Verify cycling before anything else.** Run `edl_coach.py watch --seconds 90` and
   confirm the node actually disappears and returns. If it does not, stop: the device
   is in the steady state and every capture will fail for a reason unrelated to the
   experiment.
2. **Take the fingerprint experiment first**, before any exploratory probing. It is
   the one measurement with real informational value, and it needs a healthy device.
3. **One session per capture, always closed.** With the leak fixed, that should now
   hold — but verify with `session_hygiene.py` on the first capture, not the last.

The fingerprint experiment remains the outstanding item:

```
baseline captures  ->  one Sahara upload  ->  post-upload captures  ->  diff
```

because it is the only measurement that would show what the programmer actually did in
the ~98 ms before it stops.
