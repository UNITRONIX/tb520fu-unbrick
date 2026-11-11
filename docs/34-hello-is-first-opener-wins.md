# The HELLO is first-opener-wins, and we kept resetting the port ourselves

Two corrections, both measured on 2026-11-11, both about the observer rather than
the device. The second is a repeat of the mistake already recorded in
`23-no-boot-loop.md`, which is the more useful part of this document.

---

    10|## 1. How long the HELLO actually waits

`com_attempt/ddrdata_log.txt` (the vendor tool's run) is timestamped 11:02:06. The
port had re-enumerated at roughly 11:01:48, observed independently by
`catch_hello.py`, which logged:

```
[  1.971] +APPEAR 900E
```

`QSaharaServer` opened the port at **11:02:06**, about **18 seconds** later, and
its very first read returned a complete packet:

```
STATE <-- SAHARA_WAIT_HELLO
Received 8 bytes
First few bytes: 01 00 00 00 30 00 00 00     <- HELLO_REQ, length 0x30
```

**So the HELLO is not a narrow window.** It sits in the device's buffer until
somebody opens the port and reads it. That is why the vendor tool succeeded after
an 18-second delay, and it is why "we were too slow" was never the problem.

The correct model:

```
one HELLO per boot, held until the first reader takes it.
After that, silence until the device boots again - no timer involved.
```

Consequence: any single tool may consume it, and every later tool - however fast -
gets nothing. All of 11:03-12:15 in this session was reading a buffer that had
already been emptied at 11:02:06.

## 2. The reset at the end of our own sessions

Every catcher written tonight ended its session with `SAHARA_RESET` (`0x07`) as
"hygiene". The timing in the logs is unambiguous:

```
[ 34.954]   no HELLO in 8 s
[ 34.955]   attempt finished without data      <- session ends, 0x07 sent
[ 34.971]   port disappeared after 14 ms       <- 16 ms later
```

Sixteen milliseconds between our reset and the interface vanishing. That is not
the tablet cycling. It is **the reset we just sent** re-enumerating the node.

A passive control settles it (`passive_listen.py`, zero bytes written):

```
open (DTR/RTS as pyserial sets them)
total bytes: 0
silence
the port stayed up for the whole window -> opening did not disturb it
```

**45 seconds, no disappearance, nothing written.** Then the same catch loop with
the reset removed ran 83 seconds and saw the port stay up throughout.

So in this session the device's "boot loop" was produced by the observer. This is
already the lesson of `23-no-boot-loop.md` - that a `SAHARA_RESET` makes the
device leave `900E` and re-enumerate - and it was walked into again by putting the
reset in a `finally` block where it looked like hygiene rather than a stimulus.

**Rule adopted:** a capture tool must not write a single byte unless the write is
the experiment. Close the handle and nothing else.

## 3. What this invalidates

| statement made tonight | status |
|---|---|
| "the device does not stay in 900E" | **wrong** - it does; our reset moved it |
| "the port vanishes 16 ms after a session" | true, and **caused by us** |
| "there is no HELLO on COM10" | true only after 11:02:06; before that, there was |
| "the HELLO window is too narrow to catch" | **wrong** - it persists until read |

## 4. The one thing that is actually required

A genuine cold boot is the only thing that produces a new HELLO. A
`SAHARA_RESET` is not a boot: it re-enumerates the interface without running the
firmware's Sahara init that emits the packet. Measured repeatedly.

So the sequence is:

```
1. start the catcher; it must not write anything
2. hold Power ~15 s so the tablet really powers off
3. power on
4. the catcher sees the port stabilise, opens it, and reads the HELLO
5. with that one session, read DDR_DATA first
```

`scripts/auto_grab.py` implements 1, 2, 4 and 5. Its `finally` block
deliberately does **not** send `SAHARA_RESET`, and the reason is written at the
call site so it is not "tidied up" later.
