# The dump order, and why DDR_DATA is unreachable

A precise, mechanical explanation of why the one remaining measurement cannot be obtained
with the vendor tool.

---

## 1. What the tool does

`QSaharaServer -m` reads the memory table the device hands over, then walks it
**sorted by address, ascending**. Verified from the log: the first read is the lowest
address in the table and progress is monotonic upward.

The table's DDR-related entries, sorted by address:

```
0x0080000000   DDRCS0_0.BIN        2 GiB
0x08000001e8   CD_BTDDR.BIN      256 KiB
0x0880000000   DDRCS1_0.BIN        2 GiB
0x0900000000   DDRCS1_1.BIN        2 GiB
0x0980000000   DDRCS1_2.BIN        2 GiB
0x0a00000000   DDRCS2_0.BIN        2 GiB
0x0a80000000   DDRCS2_1.BIN        2 GiB
0x0b00000000   DDRCS2_2.BIN        2 GiB
0x0b80000000   DDRCS2_3.BIN        2 GiB
0x1000000000   sbl_pmic_dump.bin 512 KiB
0x1000080000   DDR_DATA.BIN      256 KiB      <-- LAST
```

## 2. Why it never gets there

`DDRCS0_0` is the **lowest** DDR address, so it is read **first** among the big windows.
At `0x82800000` — 40 MiB in — the device returns nothing, and the tool does not skip it:

```
11:24:48: Received 0 bytes
11:24:58: Received 0 bytes
11:25:08: Received 0 bytes
... every 10 seconds, indefinitely
```

Measured over 2.5 minutes: 36 zero-byte reads, zero progress. The run has to be killed.

And `DDR_DATA.BIN` sits at `0x1000080000` — the **highest** address in the entire table.
So it is the very last thing the tool would read, behind 14 GB of windows and behind the
one window that blocks.

**The region that describes DDR training is therefore unreachable by this tool, by
construction, on this device.** Not a timing problem, not a race — an ordering consequence.

## 3. What was still learned from the full dump

Before the stall, eight windows were written. Sampling them at 4 MiB resolution:

```
DDRCS0_0   real content 0x80000000 .. 0x81c00000   28 MiB   then zeros
DDRCS1_0   real content 0x8af800000 .. 0x8bfc00000 ~260 MiB  rest 0xFF
DDRCS1_1 .. DDRCS2_3                          entirely 0xFF
```

The first window carries the boot chain — `XBL`, `SBL`, `ABL`, `UEFI`, `lapis`, `LANAI`,
`sahara`, `training`, `PMIC`, `charger` markers, plus a whole display panel configuration
(`<PanelName>VTDR6130 Visionox</PanelName>`).

The second carries a repeated `0x80438043` pattern at its head and further text markers
deep inside. So there is populated memory far above 40 MiB.

That last point kills the simplest reading of the earlier hypothesis: the programmer is not
starved of memory because there is none above 40 MiB. There is.

## 4. Three ways to reach DDR_DATA, ranked

**a) Bump to 9008 first, then dump.** In `9008` the device is in image-transfer mode rather
than crashdump, and the memory table may differ, or `DDRCS0_0` may serve fully. Untested,
cheap, no new code. **This is the next thing to try.**

**b) A custom client that requests regions in a chosen order.** The protocol allows it —
`MEMORY_READ_64` takes an arbitrary address. The obstacle is the serial-port HELLO race
documented in `28-hello-race-on-serial.md`: the tool must be the first to open the port
after a boot. Two attempts failed to win it; a third with the process already running and
polling at 50 ms has a reasonable chance.

**c) Accept that it cannot be measured** and stop treating `DDR_DATA` as required. The
training outcome is inferred as incomplete from the window map (six windows 0xFF), which is
consistent but not proof.

## 5. Bookkeeping note

During cleanup, the 16 GB of dump files were deleted **before** the 260 MiB of real content
from `DDRCS1_0` had been extracted — a path bug in the cleanup script meant the extraction
wrote to a non-existent directory and the source files were then removed.

What survived: `DDRCS0_0_first40MB.bin` (40 MiB of real memory), and the full logs
(`full_dump.log`, 20 MB; `ddrdata_log.txt`, 28 MB) which record every address, every length
and the first bytes of each transfer. The measurements above come from those logs and are
not affected.

The lost 260 MiB was a second copy of content already characterised; it can be re-dumped if
needed. Recorded here rather than glossed over, because cleanup that destroys evidence is
worth noticing even when the evidence is recoverable.
