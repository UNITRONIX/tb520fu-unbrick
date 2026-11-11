# The 900E node is silent under every transport setting — the negative is now bounded

`docs/35` recorded "zero bytes after a cold boot with one held handle". Since then
the goal has required either a fresh HELLO (route A) or a hardware entry (route B),
and both keep failing for reasons outside the host. This document closes the last
host-side variable that could explain the silence.

---

    10|## 1. What was tested this time

Previously only the default serial configuration was used. A CDC-ACM diagnostics
port can be silent for a transport reason — wrong line rate, wrong framing — and
that would look exactly like "no HELLO". So:

**Baud sweep, passive read for 1.5 s at each rate:**

```
115200 -> 0 bytes      9600 -> 0 bytes     38400 -> 0 bytes
 57600 -> 0 bytes    230400 -> 0 bytes    460800 -> 0 bytes
921600 -> 0 bytes
```

**Long passive read at the configured rate:**

```
port COM10
bytes in 20 s: 0
```

**Port identity, from the OS:**

```
COM10  Qualcomm HS-USB Diagnostics 900E (COM10)
       USB VID:PID=05C6:900E SER=B6F2DE0A LOCATION=1-4.4
```

So the node is the right one, it is bound to the right driver, and it produces
nothing at any line rate over a 20 s window.

## 2. What that rules out

| hypothesis | now |
|---|---|
| wrong baud rate for the diagnostics port | **excluded** — seven rates, all silent |
| the port needs longer than a few seconds | **excluded** — 20 s window |
| the node is a different device | **excluded** — VID/PID/serial confirm it is the tablet |
| the port is being held by another process | **excluded** — opens cleanly, no orphans |

What remains is the reading `docs/35` already reached: the node enumerates and does
not run the firmware stage that emits a packet. That is a device-side state, and no
host-side setting changes it.

## 3. Why this is worth having written down

Three times today a negative result was almost recorded as a device finding when it
was a tool finding (`docs/22`, `docs/23`, `docs/32`). This one was checked the same
way before being accepted: each layer of the transport was varied independently, and
the port identity was read from the OS rather than assumed.

The result is a bounded negative: **the silence is not a serial-configuration
problem**, and the host has no remaining lever.

## 4. Where the goal stands

The objective is `HELLO ver=3 mode=0` from PBL. Verified state at the time of
writing:

```
PID_900E present, COM10 present, bytes pending 0, no HELLO at any baud rate
```

Both routes are blocked by things the host cannot change:

- **route A** needs a fresh HELLO, which requires the firmware stage to run;
- **route B** needs the D+ condition latched before power-on, which requires a
  physical short and an unknown pin-out (`docs/45` §4).

The offline analysis has reached a natural stopping point: every condition on both
routes is reduced to a named bit, every timing question is answered, and the
remaining unknowns are physical facts (pin-out, whether a true off state is
reachable) rather than code questions.

**The next useful action is physical, and it needs the owner**: run
`scripts/vendor_entry.py` and follow the steps, starting from a genuine off state -
which `docs/51` now shows can be verified from the PON log rather than guessed.
