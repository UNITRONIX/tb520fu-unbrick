# Live state on the connected tablet

Everything above this document was static analysis. This one records what changed when
the tablet was actually probed, across several boots.

---

## 1. What was measured

`live_probe.py` took two captures 40 s apart, then `find_changing_bytes.py` took three
samples 25 s apart, on the connected unit (boot-looping, enumerating as `900E`).

### Deterministic across boots

Every scalar register was **byte-identical** in all captures:

```
RST_STAT   0x3          watchdog (b0 + b1)
PMIC_PON   0x2400200    power key
FSM_STS    0x21101
FSM_CTRL   0x43dd
DBG_EN     0x874
PMON_HIS   identical, 11 PLOG records:
             0e 00 00
             08 00 03 07 0f 70 b6
             07 00 01 04
             00 84 03 0e 00 00
             ... repeating with 03, 02, 01 ...
            08
```

The boot failure is **fully deterministic**. Whatever is wrong happens the same way
every time, down to the byte. That is consistent with a clean early return rather
than anything involving timing or power.

### Not deterministic: two regions

```
SHRM_HEAD    0x24020000..0x24022000   identical across captures
PMIC_BLOCK   0x81B75000..0x81B76000   CHANGED
OCIMEM_HEAD  0x14680000..0x14682000   CHANGED
```

`SHRM_HEAD` being byte-identical while the other two churn confirms the captures were
not taken at random moments in noise — the difference is real.

---

## 2. What changes in PMIC_BLOCK

61 bytes differ across three samples, in 14 runs. The striking part is that the same
value appears at offsets `0x0000`, `0x0010`, `0x0020`, `0x0030` and `0x0040`, changing
together:

```
sample 1   0xc91b
sample 2   0xbf18
sample 3   0xd67c
```

A register mirrored at multiple addresses is characteristic of a PMIC read through a
windowed/aliased bus: several offsets map to one hardware register.

### These are not battery voltages

Several scalings were tested against the three values:

```
raw      /12288*1.875   /1092     /8191*5
0xc91b      7.86 V      47.1 V    31.4 V
0xbf18      7.47 V      44.8 V    29.9 V
0xd67c      8.38 V      50.3 V    33.5 V
```

None lands in a plausible single-cell range. So this is **not** the VBAT reading that
would settle the battery question, and it should not be presented as one. It is some
other PMIC quantity that varies with each boot.

Note the spread: `0xbf18` to `0xd67c` is a ~12% swing between consecutive boots of the
same device. Whether that is normal variation or a symptom is unknown.

---

## 3. What changes in OCIMEM

2551 of 4096 bytes differ across three samples, in 29 contiguous runs. `OCIMEM` is the
boot ROM's internal RAM — it holds live boot state.

Some runs are almost the entire buffer (`0x0317..0x05ff` is 605 bytes). Others are
small and look like individual counters, for example at `0x07dc`:

```
sample 1   0x1963abb
sample 2   0x1959daa
sample 3   0x1976a12
```

Values in the same magnitude that rise and fall rather than increase monotonically —
consistent with a free-running timer read at different points in the loop, not with a
boot counter.

**This is the single most promising artefact found so far.** OCIMEM holds the boot
ROM's own working state, and it demonstrably differs boot to boot. If the programmer's
failure leaves a trace anywhere, this is where it would be.

What has not been done: comparing OCIMEM **after an upload attempt** against OCIMEM
**without one**. That is the experiment that would show whether the failed programmer
run leaves a distinguishable fingerprint — and the tooling for it now exists.

---

## 4. What this changes

The static analysis (`20-entry-point-spin.md`) says the programmer's `main` returns
normally and the entry code stops without checking the result. That predicted a fully
deterministic failure — and the live measurements confirm the deterministic half:
every scalar register and the PLOG history are identical across boots.

It does **not** confirm the "returns with an error code" half. That requires seeing the
programmer's own state after its run, and OCIMEM is where to look.

---

## 5. The experiment worth running

```
1. capture OCIMEM + PMIC_BLOCK with the device idle in its boot loop     (baseline)
2. perform one Sahara upload of the melf, as every previous attempt did
3. capture the same regions again as soon as the device is back in 900E
4. diff
```

A region that differs between an idle boot and a post-upload boot is the programmer's
fingerprint. With 2551 bytes already varying between idle boots, the comparison needs
more than one sample per side, but the tooling supports that.

That is the next thing to run, and it needs the tablet connected — which it is.
