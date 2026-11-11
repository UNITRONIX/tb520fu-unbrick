# The device does not boot-loop — it waits in 900E

A correction to an assumption that has shaped every capture tool in this repository,
and that produced several wrong conclusions.

---

## 1. The wrong assumption

Earlier notes — and all the tooling written tonight — treat the tablet as
**boot-looping**:

```
900E present ~40-50 s  ->  absent ~12-15 s  ->  900E present  ->  repeat
```

and the pattern is real: `edl_coach.py watch` observed exactly that, with timestamps.

The mistake was in attributing it to the device. **The loop only happens because
something resets it.** Left alone, the tablet sits in `900E` indefinitely and does
nothing.

Correct as of this session, confirmed by the owner and by measurement: without an
explicit bump, `900E` persists. A bump is required to reach `9008`.

## 2. Why the loop appeared

Every one of these sends something to the device, and several send `SAHARA_RESET`:

- `check_tablet.py` probes with a HELLO and closes;
- `session_hygiene.py` opens, closes, reopens;
- `live_probe.py`, `find_changing_bytes.py`, `timing_window.py` each open a session;
- `probe_pattern.py` reads a HELLO per attempt.

A `SAHARA_RESET` or a completed handshake is enough to make the device leave `900E`
and re-enumerate. So the "boot loop" was, at least in part, **the measuring apparatus
resetting the device**.

That is a serious methodological error and it is worth naming plainly: the observation
was real, the interpretation was backwards. The device was not cycling; the tools were
cycling it.

## 3. What this invalidates

Every helper that waits for an absence before capturing. In `upload_fingerprint.py`,
`baseline_capture.py`, `find_changing_bytes.py`, `live_probe.py`:

```python
while ...:
    if usb.core.find(idVendor=0x05C6, idProduct=0x900E) is None:
        break          # wait for absence
```

Against a device that never leaves `900E` on its own, this either waits forever or
times out. Several runs "failed to capture" for this reason, and the failures were
recorded as device problems.

## 4. The correct sequence

```
1. confirm 900E is present
2. bump: HELLO(ver) -> HELLO_RSP(mode=3) -> CMD_READY
         -> SWITCH_MODE(0) -> HELLO_REQ -> HELLO_RSP(mode=0) -> END -> DONE
3. wait for 9008 to enumerate  (~20 s measured)
4. do the work at 9008
```

After a bump the device **is** at `9008` and answers `HELLO ver=3 mode=0` — verified
this session, twice. That is the state in which a programmer can be uploaded, and it
is reached reliably.

## 5. What this means for the outstanding experiment

The fingerprint test — baseline captures, one upload, post-upload captures, diff —
does not need the device to cycle. It needs:

```
900E  ->  capture baseline  ->  bump to 9008  ->  upload  ->  back to 900E  ->  capture
```

and after the failed upload the device returns to `900E` by itself, where it waits.
That is *easier* than what the tools were built for, not harder.

## 6. Honest note

This correction came from the device owner stating a fact I had not questioned: that
the tablet will sit in `900E` forever unless bumped. The measurement that "confirmed" a
boot loop was mine, and it was confounded by my own resets. Recording that because the
same trap — trusting an observation whose cause is the observer — is what produced the
earlier "device stopped cycling" false alarm as well.

---

## 7. Reaching 9008, and getting back

Measured this session:

```
900E  --bump-->  9008      works, twice, ~20 s to enumerate
9008  --SAHARA_RESET-->   does NOT return to 900E
```

The bump is reliable. The reverse is not: sending `SAHARA_RESET` at `9008` left the
device at `9008` and mute, requiring a power cycle.

That has a practical consequence for any experiment that needs both states:

- the baseline must be captured **before** the bump, while the device is still at 900E;
- after the upload the programmer resets the device itself, which is what returns it to
  900E — observed repeatedly in earlier sessions (`DONE` -> ~8 s -> absent -> 900E);
- so the order is: `900E capture -> bump -> upload -> (device returns to 900E) -> capture`.

Do **not** try to "reset back" to 900E manually. There is no working path for that, and
attempting it wedges the node.

## 8. Tooling that must be rewritten

| script | assumption | status |
|---|---|---|
| `upload_fingerprint.py` | waits for absence before captures | needs rewriting |
| `baseline_capture.py` | waits for absence | needs rewriting |
| `timing_window.py` | treats absence as normal | still useful as a state probe |
| `live_probe.py` | retries across "cycles" | retries are wasted; the device does not cycle |
| `find_changing_bytes.py` | same | same |
| `fingerprint_v2.py` | correct order, but does not handle 9008-start | partial |

`fingerprint_v2.py` is the closest to correct and is the one to finish.

