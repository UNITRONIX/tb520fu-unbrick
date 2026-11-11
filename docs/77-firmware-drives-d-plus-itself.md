# The firmware drives D+ itself, on every boot — which changes the timing requirement for route B

`docs/41` reduced the FEDL condition to one bit of a status word, and `docs\18` said the
short must be applied before power-on. A detail in both captured boot logs refines that
and makes the requirement easier, not harder.

---

    10|## 1. What the log shows

Both boots, at a consistent point after charger detection:

```
A   B -    599874 - usb: chgr -  CDP_CHARGER
A   B -    800716 - usb: usb_dp_toggled_for_cdp , 0xc8

B   B -    503890 - usb: chgr -  CDP_CHARGER
B   B -    704733 - usb: usb_dp_toggled_for_cdp , 0xc8
```

`0xc8` is 200, and the field is a time in milliseconds: the delay between the two
lines is 800 716 − 599 874 = 200 842 µs in boot A, and 704 733 − 503 890 = 200 843 µs
in boot B. **The same 200 ms, to within a microsecond, on two different boots.**

## 2. What that means

`usb_dp_toggled_for_cdp` is not a passive read. The firmware:

1. detects a charger and classifies it as **CDP** (charging downstream port),
2. then **toggles the D+ line itself**,
3. and waits exactly 200 ms doing it.

So the D+/D− pair is **actively driven by the SoC's USB PHY during early boot**, on
every boot, regardless of what is connected.

That matters for route B for two reasons.

**First, it explains why a short can be detected at all.** If D+ were only an input, an
external short would have no defined effect. Because the firmware drives the line and
watches it, an externally applied low is something the PHY comparison can actually
observe - which is consistent with `docs\18`'s claim that an EDL cable worked once.

**Second, it widens the window.** `docs\18` concluded the poll was ~50 ms and therefore
untimeable. But the sequence above shows the PHY is **actively exercising D+ for at
least 200 ms** on every boot, before DDR init. A short held across that whole period is
present during a much longer active window than 50 ms.

## 3. Reconciling with `docs\41`

`docs\41` found the *decision* is a single masked read of a status word:

```
and w8, w0, #0x30000
cmp w8, #0x10000
```

That is still true - the decision has no duration. What this document adds is that the
**condition feeding it** is produced by the PHY toggle, and the toggle lasts ~200 ms
rather than ~50 ms.

So the practical instruction sharpens:

```
before: "hold D+ low; the window is ~50 ms, so it must already be there"
now:    "hold D+ low through power-on and keep holding; the PHY exercises the line
         for ~200 ms and then continues to DDR init"
```

## 4. What is not claimed

- The 200 ms figure is the **measured gap between two log lines**, not a decoded
  constant in the code. It is the same on both boots, which is why it is credible as a
  designed delay rather than coincidence.
- Whether the toggle *is* the FEDL detection mechanism is **not established**. It may be
  CDP enumeration (a charger-protocol handshake) that happens to also be visible to the
  FEDL check, or the two may be unrelated. The coincidence of timing is suggestive and
  nothing more.
- The `usb_dp_toggled_for_cdp` code site was located (`0x148798c4`) but reading it was
  not completed - two attempts landed on shifted offsets and produced PHY-configuration
  code instead of the function body.

## 5. Practical consequence, unchanged in direction

Route B still needs a physical short and still needs a pin-out we do not have. But the
requirement on the operator is **less precise than feared**: hold the short from before
power until the device enumerates, and the firmware will be actively driving and
sampling D+ during that time.

That is worth knowing before the next physical attempt, and it cost nothing to find -
both log lines were already in the dump.
