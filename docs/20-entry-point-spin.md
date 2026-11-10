# The programmer's entry point spins on an exception flag

This is the most specific finding in the project so far. It identifies a concrete
code path in the programmer that produces silence followed by a watchdog reset —
the exact symptom measured on this tablet.

---

## 1. Why the entry point was never read before

Every earlier investigation started from the protocol: Sahara, upload, `END`, `DONE`,
then "nothing". The programmer was treated as a black box that failed to bind USB.

Nobody disassembled its **entry point**. `scripts/firehose_entry.py` does, and the
first forty instructions are not what one expects from working firmware.

Two things had to be fixed before this was readable:

- the ELF entry is `0x149997a8`, not the start of the segment;
- `a64.py` had a bug that rendered `MSR` as `MRS`, which made the whole sequence
  look like meaningless register reads.

The second is worth stating plainly: the decoder was wrong in a way that produced
plausible-looking output. `0xD5181000` is `msr SCTLR_EL1, x0`, not a second
`mrs`. The disambiguation is bit 21 (`L`): set means read.

---

## 2. The sequence

```
0x149997c0  mov  x7, x0              save the incoming argument
0x149997c4  movz x0, #0x0
0x149997c8  add  sp, x0, #0x0        SP = 0
0x149997cc  dmb  ishld   (x4)
0x149997dc  mrs  x0, SCTLR_EL1
0x149997e0  and  x0, x0, #~1         clear M   (MMU off)
0x149997e4  and  x0, x0, #~4         clear C   (data cache off)
0x149997e8  orr  x0, x0, #8          set   I   (IRQ masked)
0x149997ec  msr  SCTLR_EL1, x0
0x149997f0  dmb  ishld   (x2)
0x149997f8  (literal load)
0x149997fc  msr  s3_0_c12_c0_0, x0   VBAR_EL1 <-- x0 is NOT a vector table
0x14999800  mrs  x0, s3_0_c1_c0_2    CPTR_EL3
0x14999804  orr  x0, x0, #0x300000
0x14999808  msr  s3_0_c1_c0_2, x0    allow FP/SIMD
0x1499980c  dmb  ishld
0x14999810  mrs  x0, s3_0_c12_c1_0   ISR_EL1
0x14999814  and  x0, x0, #0x100      isolate bit 8
0x14999818  cbnz x0, 0x14999868      taken if bit 8 set
0x1499981c  ...
0x1499982c  mrs  x0, SCTLR_EL1
0x14999830  orr  x0, x0, #0x1000     enable I-cache
0x14999834  orr  x0, x0, #0x800000   enable BTB
0x14999838  msr  SCTLR_EL1, x0
```

and the branch target:

```
0x14999868  b 0x14999868             an unconditional branch to itself
```

---

## 3. What each observation means

### SP is set to zero

```
movz x0, #0x0
add  sp, x0, #0x0
```

Setting the stack pointer to `0` is not a normal function prologue; it is part of a
loader convention where the incoming `x0` carries a pointer to a boot context
structure, and the entry code relocates itself before establishing a real stack. The
argument is saved in `x7` at the top, which supports that reading — the value is
kept, but not used to place the stack.

### VBAR is set correctly — an earlier reading of this was wrong

The literal loads resolve as follows:

```
0x149997f8  LDR x0, =0x14999000    -> literal at 0x14999870 holds 0x14999000
0x149997fc  msr VBAR_EL1, x0
```

`0x14999000` is the **start of image [3]'s executable segment** (ph[1] vaddr). So the
exception vectors are pointed at the image base, which is the normal convention.

> **Correction.** An earlier draft of this document claimed VBAR was being written
> from the SCTLR value and therefore pointed at garbage. That was wrong: `x0` is
> reloaded from a literal at `0x149997f8` before the `msr`. The decoder printed that
> literal load as `?`, which hid the reload. This is the third time in this project
> that an unexplained `?` in a listing concealed a value that changed the meaning of
> the surrounding code.

### The exception check is real, and its failure path is a self-loop

```
0x14999810  mrs  x0, ISR_EL1
0x14999814  and  x0, x0, #0x100
0x14999818  cbnz x0, 0x14999868
```

`ISR_EL1` bit 8 is an exception-pending flag. If it is set, the code branches to
`0x14999868`, which is `b .`, an unconditional branch to itself.

**An infinite tight loop with interrupts masked produces exactly the observed
behaviour:** no USB descriptor is ever raised, the CPU does not service the
watchdog, and after the watchdog window the SoC resets. Measured on this unit: 8.016 s,
against a watchdog window of 7.918 s ±3 ms.

### The normal path continues into BSS clearing

If the exception bit is clear, the code proceeds:

```
0x14999824  LDR x0, =0x149da000     start of the BSS segment (ph[4] vaddr)
0x14999828  add sp, x0, #0x0
0x1499982c  mrs x0, SCTLR_EL1
0x14999830  orr x0, x0, #0x1000     enable I-cache
0x14999834  orr x0, x0, #0x800000   enable BTB
0x14999838  msr SCTLR_EL1, x0
0x1499983c  LDR x0, =0x149d7000     end of BSS
0x14999840  LDR x1, =0x3000         length
0x14999844  and x1, x1, #~0xF
0x14999848  movz x2, #0
0x1499984c  stp sp, sp, [x0], #0x10 zero 16 bytes
0x14999850  add x2, x2, #0x10
0x14999854  cmp x1, x2
0x14999858  b.ne 0x1499984c          loop until done
0x1499985c  mov w0, w7               restore the saved argument
0x14999860  bl 0x14999c4c            call the real entry
0x14999864  bl 0x14999868            (falls into the same self-loop)
```

That is a textbook freestanding startup: relocate the stack, configure caches,
enable the exception vectors, clear BSS, restore the argument, jump to `main`. It
looks correct.

**Which makes the finding sharper, not weaker.** The startup code is normal. The
only abnormal outcome is the branch at `0x14999818`, taken because `ISR_EL1` bit 8
was already set when the entry code ran.

That means **the fault happened before the programmer's own code started** — the
exception was pending on entry, inherited from whatever ran before it.

### And the self-loop is reachable by two routes

Note `0x14999864`: the normal path, after returning from `main`, also branches to
`0x14999868`. So the self-loop is the intended "we are finished, stop" behaviour —
hitting it from the exception check is the abnormal case.

This has a testable consequence that costs nothing: **if `main` returned quickly
rather than hanging, the symptom would be identical.** A `main` that returns
immediately produces the same silence as an immediate exception. From outside, a
crash and a clean early return are indistinguishable.

---

## 4. Why this is consistent with everything already measured

| observation | explanation under this finding |
|---|---|
| Sahara upload succeeds, `END 0x00`, `DONE` acked | PBL accepts the melf before any of this runs |
| ~8.0 s of silence, no Firehose endpoint | the CPU is spinning in `b .` with IRQ masked |
| watchdog reset, not a power-down | `b .` does not stop the WDT |
| exact repeatability | a deterministic branch taken the same way each boot |
| no 8-second delay exists in the code | confirmed — the only delay above 50 ms is 50 ms |
| four tool chains, two OSes, identical result | the fault is inside the device, after `DONE` |

The last row is the important one: it explains why no host-side change ever made a
difference. The host was never the variable.

---

## 5. What is still uncertain

Being precise about the limits of this finding:

- **The trigger is not proven.** The code path is identified and it produces the
  right symptom, but what sets `ISR_EL1` bit 8 on this unit is not established.
  A plausible candidate is the misconfigured `VBAR_EL1` causing a fault, but that is
  inference, not measurement.
- **The `x0` convention is inferred** from the shape of the code (save to `x7`, zero
  the stack, relocate). It is a standard loader pattern, not something read out of
  this binary.
- **`0x149997f8` is a literal load that was not decoded** by the current decoder
  (listed as `?`). It sits between the SCTLR write and the VBAR write and may load
  the intended vector value — if so, the VBAR observation needs revisiting. This is
  the single most important open detail.
- **Whether the same path is reached on a healthy device.** It must be, if it is the
  normal entry — which would mean the difference is in the state it inherits, not in
  the code.

---

## 6. The next question, stated narrowly

Decode `0x149997f8`. It is a PC-relative literal load, and what it loads determines
whether `VBAR_EL1` receives a real vector table or garbage. Three outcomes:

1. it loads a valid vector address that is then overwritten by the SCTLR value —
   indicating a genuine bug in this build;
2. it loads something that makes the sequence coherent and shifts the explanation
   elsewhere;
3. it cannot be resolved statically because the value is patched at load time — in
   which case the entry code depends on the loader and the melf's image [4] layout
   becomes relevant.

That is a bounded, offline question, and it is the one to answer next.

---

## 7. Answered: the literal loads, and what they change

The literal loads resolve cleanly:

```
0x149997f8  LDR x0, =0x14999000    literal @ 0x14999870   -> VBAR base, correct
0x14999824  LDR x0, =0x149da000    literal @ 0x14999878   -> BSS start
0x1499983c  LDR x0, =0x149d7000    literal @ 0x14999880   -> BSS end
0x14999840  LDR x1, =0x3000        literal @ 0x14999888   -> BSS length
```

`VBAR_EL1` is pointed at `0x14999000`, the executable segment base — the normal
convention. **The earlier "VBAR gets garbage" reading was wrong** and is corrected in
§3.

The startup code is therefore entirely conventional: relocate stack, disable MMU,
configure caches, install vectors, clear 0x3000 bytes of BSS, restore the saved
argument, call the real entry.

## 8. What main does, and why the self-loop is not a bug

Following the call at `0x14999860`:

```
0x14999c4c  b 0x14999c08                    thin trampoline
0x14999c08  sub sp, sp, #0x20
0x14999c14  adrp x8, 0x6d000
0x14999c18  adrp x0, 0x80200000
0x14999c24  and  x2, x8, #0xffffffff        x2 = 0x6d000
0x14999c28  mov  w1, wzr                    x1 = 0
0x14999c30  bl   0x1499c130                 memset(0x80200000, 0, 0x6d000)
0x14999c34  bl   0x149999dc                 early init
0x14999c3c  bl   0x149a31d0                 XML layer init
0x14999c40  ldp  x29, x30, [sp, #0x10]
0x14999c44  add  sp, sp, #0x20
0x14999c48  ret                             <-- RETURNS
```

`0x149a31d0` is unmistakably the XML layer: it references
`"Can't decode attribute %s with value %s"` and the attribute decoder at `0x149a3230`.

**So `main` runs to completion and returns.** The self-loop at `0x14999868` is not an
error path from the exception check — it is the intended "entry function finished,
stop here" behaviour. Both routes into it (`0x14999818`, `0x14999864`) are legitimate.

This inverts the reading in §3 and matters a great deal:

- the programmer **does** reach its XML layer;
- `main` **does** return rather than blocking;
- the CPU then sits in `b .` **by design**, waiting for an interrupt or reset.

From outside that is indistinguishable from a hang — no USB traffic, watchdog
expires — but the cause, and therefore the remedy, is different.

## 9. The silent-failure hypothesis

`main` accumulates its results into `w19`:

```
0x14999c98  bl  0x149b1b10
0x14999c9c  orr w19, w0, w19
0x14999ca0  bl  0x14999cd4
0x14999ca4  orr w19, w19, w0
0x14999ca8  bl  0x149b0718
0x14999cac  bl  0x149b0938
0x14999cb0  orr w0, w19, w0          <- the accumulated status
0x14999cb4  b   0x14999cc8
0x14999cc8  ldp / ret                <- returned to the caller
```

So `main` returns an accumulated error code in `w0`. The entry code at `0x1499985c`
restores `w0` from `x7` and calls `main`, then falls straight through to the
self-loop **without examining the result**:

```
0x1499985c  mov w0, w7
0x14999860  bl  0x14999c4c
0x14999864  bl  0x14999868          <- straight into b .
```

**A programmer whose every initialisation step failed would return normally, with a
non-zero error code that nobody reads, and then stop.** That is a total failure that
is externally identical to a clean shutdown — and it fits every measurement:
no USB, no XML, no watchdog servicing, reset at the window.

This is the most plausible explanation found so far, and unlike the earlier
hypotheses it is testable from the host: the accumulated status is computed in plain
registers before the return.

