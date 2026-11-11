# TZ has the cookie register in its access-control table, and no code that sets bit 12

`docs/70` narrowed the search for whoever sets the download request bit to three
candidates and named `tz.mbn` as the only readable one. It has been searched. The
result is a partial answer and a clean negative.

---

## 1. One reference, and it is not code

`tz.mbn` is a 4 137 440-byte ELF with 41 program headers. Searching it for the
4-byte little-endian value `0x01FD9000`:

```
occurrences: 1, at file offset 0x1ADD38
```

The surrounding bytes are a **table of 16-byte entries**, each a
`(address, attributes)` pair with the high half being `0x80800000` / `0x80800001`:

```
0x1ADD38   0x8080000101FD9000      lo = 0x01FD9000   hi = 0x80800001
0x1ADD48   0x808000001760041C      lo = 0x1760041C
0x1ADD58   0x8080000017600420      lo = 0x17600420
0x1ADD68   0x8080000017600434      lo = 0x17600434
0x1ADD78   0x8080000017800058      lo = 0x17800058
...
```

This is an **access-control / resource-ownership table**, not executable code. It
records that `0x1FD9000` is a resource TrustZone is responsible for, alongside other
regions in the `0x146xxxxx`/`0x176xxxxx`/`0x178xxxxx` ranges.

That is consistent with `docs/66`: the cookie cannot be written by the AP directly,
and TZ is the party that owns it.

## 2. What is not there

**No code in `tz.mbn` references `0x1FD9000`.** The only occurrence is the table
entry. There is also no `dload` / `DLOAD` / `EDL` / `cookie` string anywhere in the
image.

So `tz.mbn` **owns** the register but does not contain a routine that sets bit 12.
Whatever TZ service the AP calls (`TZ_IO_ACCESS_WRITE_ID`, `docs/66`) is generic: it
takes an address and a value, and the *decision* about the value is made by the
caller.

That puts the decision back on the AP side - and `docs/70` showed the only AP-side
code that exists in the melf never sets bit 12.

## 3. What this leaves, honestly

```
XBL (image[2])        reads bit 12, never sets it             measured, exhaustive
TZ  (tz.mbn)          owns the register, no bit-12 code      measured
stock UEFI            would write it, but is not installed   docs/67
PBL (boot ROM)        unreadable                             -
```

The remaining possibilities, in order of how much they explain:

1. **The bit was set once, long ago, and never cleared.** The register is in the
   always-on domain. A value written before the brick - by the stock UEFI that *was*
   installed then - would persist. That single sentence accounts for every
   observation in this session, including why `boot_dload_entry` was reached once and
   never again.
2. **PBL sets it**, in response to a condition that has since stopped occurring.
   Unreadable from the host, no evidence either way.
3. **The generic TZ write service is called by code outside the melf**, e.g. a
   partition's bootloader. This is the same as (1) in practice.

**Nothing in the readable firmware can set the bit today.** That is now an
established negative across XBL and TZ together.

## 4. Consequence for the goal

The goal is `HELLO ver=3 mode=0`. The route through the cookie requires bit 12 set,
and:

- no readable code sets it,
- it cannot be written from the host without a session,
- and the session is what the goal would provide.

**That is a closed loop.** The cookie route cannot bootstrap itself.

Which makes the assessment of the remaining routes sharper:

| route | dependency |
|---|---|
| cookie -> `boot_dload_entry` | blocked by an unsettable bit (this document) |
| **FEDL by hardware short** | **does not need the cookie at all** (`docs/41`, `docs/42`) |
| EUD | needs a debug policy that no DTB declares (`docs/42` route C) |
| bump 900E -> 9008 | needs a HELLO, which is what is missing (`docs/35`) |

Three of the four depend on something the host cannot supply. **FEDL is the only
route that depends on nothing but the connector** - and `docs/41` reduced its
condition to `(status & 0x30000) == 0x10000`, one bit read from a latch that a
physical short can set before the firmware looks.

## 5. Status

Goal unchanged and not achieved. What this document adds is the closing of the
cookie avenue with evidence from both readable firmware images, and a clearer ranking
of what is left: **the hardware short is now the only route that does not require
something already broken to work.**
