# The 40 MiB DDR capture: it is a mapping with holes, not a truncated window

First real DDR contents obtained for this tablet. It corrects the previous document's
conclusion.

---

## 1. What was captured

`DDRCS0_0_first40MB.bin` — 40 MiB from `0x80000000`, read with `QSaharaServer` in
`SAHARA_MEMORY_DEBUG` over the COM port.

Content classification by 4 KiB page:

```
code        1870 pages   7.3 MiB   18.3%
zeros       4745 pages  18.5 MiB   46.3%
0xFF        3055 pages  11.9 MiB   29.8%
data         376 pages   1.5 MiB    3.7%
sparse       194 pages   0.8 MiB    1.9%
```

**7.3 MiB of real AArch64 code.** The first bytes decode as valid instructions:

```
0x80000000  d283000a  mov  x10, #0x1800
0x80000004  f2a6080a  movk x10, #0x3040, lsl #16
```

## 2. The correction

`26-ddr-wall-at-40mb.md` concluded that DDR "presents 40 MiB and nothing beyond", and
suggested an out-of-memory condition in the programmer. **That framing was too simple.**

The 40 MiB is not a contiguous block of working memory that stops. It is a **sparse map**:
real code and data at specific addresses, with fill in between.

```
0x80000000 .. 0x80200000    code        boot chain (XBL and friends)
0x80200000 .. 0x80800000    'W' fill    a test pattern buffer, not memory
0x81A00000 .. 0x81B00000    code        XBL/SBL/UEFI, panel config
0x81AD0000 .. 0x81CE0000    data        configuration blobs
```

The `W` runs are the giveaway: 100-character runs of the ASCII letter `W` at
`0x80292000`, `0x8028c000`, `0x80811000` and others. That is **not** uninitialised memory
and **not** code — it is a memory test pattern that was never cleared.

So the region is mapped, but much of it holds test data rather than live state. The
boundary at `0x82800000` is real and still measured, but it is the edge of what the crash
handler will serve, not necessarily the edge of usable DRAM.

## 3. What the capture does prove

Real, identifiable content is present:

```
XBL       0x800eb2bb  0x81a0069f  0x81a006c1
SBL       0x81a006fe  0x81a0071b  0x81a01e9e
ABL       0x800e15da  0x800e2d06  0x800e39a4
UEFI      0x81a0cb4c  0x81a0cf6c  0x81a0d018
lapis     0x81adf9fa  0x81adfa0f  0x81adfa30     <- the device codename
LANAI     0x80200208  0x8024aae4  0x80254864     <- the platform name
sahara    0x81ad4868  0x81ad4ca7
watchdog  0x800e12e5  0x800e26c9
training  0x81a019af  0x81ad6c9b  0x81b17115
```

and a full display configuration blob:

```
0x81ae8246  <?xml version="1.0" encoding="utf-8"?>
            <PanelName>VTDR6130 Visionox</PanelName>
0x81ae7d32  <?xml version="1.0" encoding="utf-8"?>
            <PanelName>VirtioDSI</PanelName>
```

That last one matters: the device has **bound a real display panel and written its
configuration into memory**. The hardware initialisation path that produces this runs
before the point where the programmer fails.

## 4. What this changes about the failure hypothesis

The previous document proposed: *the programmer believes it has 2 GiB and only 40 MiB
answers, so it dies of memory exhaustion.*

That is now **less certain**, because 40 MiB of *mapped* memory containing 7.3 MiB of live
code and working panel configuration is not the picture of a machine whose memory is
broken. It is the picture of a machine whose crash handler exposes a limited region.

What remains true and measured:

- DDR CS0 serves exactly 40 MiB and then nothing (`0x82800000` is the first dead
  address, verified twice);
- the other seven declared windows return `0xFF` throughout;
- the boot chain, display configuration and Sahara code are all resident and correct.

## 5. The honest reading

Two explanations survive and this capture does not separate them:

**a)** the crash handler only maps 40 MiB of CS0 by design, and the real DRAM is fine —
in which case the 40 MiB limit says nothing about the programmer's failure;

**b)** CS0 genuinely only trains to 40 MiB, and the rest of the declared 16 GiB is absent —
in which case the programmer runs out of the memory it was promised.

The discriminator is `DDR_DATA.BIN`, the region the memory table calls **"DDR Training
Data"** (`0x1000080000`, 256 KiB). Training data describes the ranks it configured. If it
describes all eight windows, (a) is likely and the DDR is not the fault. If it describes
fewer, (b) is confirmed.

That read has not succeeded yet: the sessions keep being consumed by the full dump before
reaching it. It needs a session that asks for **only** that region, which is what
`Read-DdrData.ps1` attempts — with `-m` and no programmer, so the dump order is not driven
by a full-memory sweep.

## 6. Value kept

`DDRCS0_0_first40MB.bin` (40 MiB) is retained as `com_attempt/DDRCS0_0_first40MB.bin`. It
is the only real memory capture for this device and it contains the running boot chain —
useful for any future analysis of what the device actually executes.

The 14 GB of `0xFF` fill was deleted. It carried no information.
