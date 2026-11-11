# What the full DDR dump actually contains

Sixteen gigabytes dumped. This is what is in it, measured rather than assumed.

---

## 1. Six of eight windows are unmapped

Sampling every window at 4 MiB resolution:

```
DDRCS0_0  0x80000000    real content   0x80000000 .. 0x81c00000    28 MiB
DDRCS1_0  0x880000000   real content   0x8af800000 .. 0x8bfc00000  ~275 MiB
DDRCS1_1  0x900000000   entirely 0xFF
DDRCS1_2  0x980000000   entirely 0xFF
DDRCS2_0  0xa00000000   entirely 0xFF
DDRCS2_1  0xa80000000   entirely 0xFF
DDRCS2_2  0xb00000000   entirely 0xFF
DDRCS2_3  0xb80000000   entirely 0xFF
```

**Two windows carry data. Six are unmapped.** That is the real shape of this machine's
memory map, and it is not what the device's own table advertises — the table declares all
eight as 2 GiB of DDR.

## 2. What the first window contains

`DDRCS0_0` at `0x80000000`, 28 MiB of real content:

```
0x80000000  d283000a  mov  x10, #0x1800     valid AArch64 from the first byte
            ARM64-plausible ratio: 83%
```

Markers found:

```
XBL       0x800eb2bb, 0x81a0069d
SBL       0x81a006fc, 0x81a00719
ABL       0x800e15da, 0x800e2d06        <- the partition the whole plan was about
UEFI      0x81a0cb4c, 0x81a0cf6c
lapis     0x81adf9fa                     <- device codename
LANAI     0x80200208                     <- platform name
sahara    0x81ad4868
training  0x81a0197e, 0x81ad6c9b
PMIC      0x800efdfa, 0x81a00cd3
charger   0x81a01d32, 0x81a102bc
```

plus long runs of the ASCII letter `W` at `0x80292000`, `0x8083e000` and others — the
memory test pattern noted earlier.

## 3. What the second window contains, and why it matters

`DDRCS1_0` at `0x8af800000`. The head is:

```
0x8af800000  80438043 80438043 80438043 80438043
```

`0x80438043` repeated without end. **That is not code.** My classifier called it "100%
ARM64-plausible" because the pattern happens to decode as sane instructions — a good
reminder that instruction-likeness is not proof of instruction.

Further in, at `0x8bb01cc1d`, `0x8bc31c21b`, `0x8bd653cf0`:

```
XBL, SBL, ABL, DDR, USB
```

**Text identifying the boot chain appears inside the second DDR window**, at addresses
hundreds of megabytes above the first. Combined with the head being a repeated pattern,
the most plausible reading is a **relocated or duplicated copy** of boot structures high in
CS1 — the kind of thing a memory test or a decompression buffer leaves behind.

## 4. What this changes

The previous document (`27-ddr-is-a-sparse-map.md`) said the map is sparse. That holds and
is now quantified: **two populated windows out of eight declared.**

But the earlier hypothesis — "the programmer dies because it only has 40 MiB" — does not
survive contact with this data. There is a **second populated region** far above 40 MiB.
Whatever limits the programmer, it is not simply "no memory past 40 MiB".

What the data does support:

- the boot chain (XBL, SBL, ABL, UEFI) is resident and identifiable;
- the platform has bound a display panel and written its configuration;
- four separate `W`-fill test regions exist, meaning memory testing ran and its pattern was
  never cleared;
- six windows are unmapped, which is a great deal of DRAM to be absent on a 16 GiB device.

## 5. The honest state of the hypothesis

| claim | status |
|---|---|
| DDR CS0 serves 40 MiB then nothing | **measured**, twice, independent sessions |
| six of eight declared windows are unmapped | **measured** from the full dump |
| a second populated region exists high in CS1 | **measured** |
| the programmer fails for lack of contiguous memory | **not supported any more** — there is memory at `0x8af800000` |
| DDR training is incomplete | **still untested** — `DDR_DATA.BIN` was never reached, because the dump stalls at `0x82800000` and never advances |

## 6. Why `DDR_DATA.BIN` remains the key

The dump reaches `DDRCS0_0`, issues the request at `0x82800000`, receives nothing, and
**stops there permanently** — 36 zero-byte reads and no progress, observed over 2.5
minutes. It never reaches entries 41-53 of the table, which include `DDR_DATA.BIN`.

So the region that describes DDR training is unreachable by this route, and it is the one
artefact that would settle whether training completed for all ranks.

Two options remain, both unglamorous:

1. a device state where CS0 does not stall — e.g. immediately after a bump to `9008` rather
   than from `900E`;
2. a tool that requests regions in a chosen order. `QSaharaServer` walks the table in
   reverse and offers no filter; a custom client can ask for any region first, but only if
   it wins the HELLO race on the serial port (`28-hello-race-on-serial.md`).

## 7. Worth keeping

The 16 GB dump is deleted; it is 0xFF and carries nothing. The extracted 28 MiB and 260 MiB
of real content are worth keeping as the only memory images of this device in existence.
