# Gate 1 is a lazy initialiser, not a hardware condition

`docs/60` consolidated three gates in the EDL decision chain and left gate 1
undecoded (`bl 0x14855fbc` with argument 1). It is now read, and it changes the
picture: gate 1 is not a hardware test at all.

---

    10|## 1. The function

`0x14855fbc`, entry and early exits:

```
0x14855fbc  stp  x29, x30, [sp, #-0x30]!
0x14855fc8  add  x29, sp, #0x0
0x14855fcc  adrp x20, 0x148f6000
0x14855fd0  ldr  x8, [x20, #0x5b0]      <- is a pointer already set?
0x14855fd4  cbz  x8, 0x14855ff0         <- no: go and initialise
0x14855fd8  mov  w19, wzr
0x14855fdc  mov  w0, w19                <- return 0
0x14855fe4  ldp  x20, x19, [sp, #0x20]
0x14855fec  ret
```

and the initialising branch:

```
0x14855ff0  adrp x8, 0x148c3000
0x14855ffc  add  x8, x8, #0x6b8
0x14856000  add  x9, x9, #0x6f8
0x14856004  cmp  w0, #0x0               <- the argument
0x14856008  add  x21, x21, #0x5a8
0x1485600c  csel x8, x9, x8, hi         <- pick one of two callbacks by argument
0x14856014  movz w0, #0x40
0x14856018  str  x8, [x21, #0x0]        <- store the chosen callback
0x1485601c  bl   0x14857818             <- real initialisation
0x14856020  mov  w19, w0
0x14856024  cbnz w0, 0x14856124         <- failure path
0x14856028  ldr  x8, [x21, #0x8]
0x1485602c  cbz  x8, 0x14856124
0x14856030  str  sp, [x8, #0x0]
0x14856034  ldr  x8, [x20, #0x5b0]
0x14856038  stp  sp, sp, [x8, #0x8]     <- zero a structure
0x14856040  stp  wzr, wzr, [w8, #0x28]
0x14856044  strh wzr, [x8, #0x30]
0x1485604c  bl   0x14855e28             <- continue init
```

## 2. What it does

It is a **two-state initialiser**:

```
state 1: [0x148F65B0] == 0    -> not yet initialised -> run the init, store a callback
state 2: [0x148F65B0] != 0    -> already initialised -> return 0 immediately
```

`adrp x20, 0x148f6000` + `[x20, #0x5b0]` gives the flag at **`0x148F65B0`**, in the
same `0x148Fxxxx` config block as `dload_entry_count` at `0x148F0080`
(`docs/59`).

The argument selects between two callbacks (`0x148C36B8` and `0x148C36F8`) via
`csel ... hi`, i.e. argument 1 picks the second.

## 3. What this means for gate 1

Back in `docs/60`'s chain:

```
0x148311e8  movz w0, #0x1
0x148311ec  bl   0x14855fbc
0x148311f0  cbz  w0, 0x14831214         -> continue to the EDL work
0x148311f4  ... log + error path
```

With the function read: it returns **0 when the subsystem is already initialised**,
and **non-zero only if initialisation fails**.

So gate 1 reads:

```
if (subsystem already initialised)   -> proceed with the EDL work
else if (initialise it successfully) -> proceed (returns 0)
else                                 -> error path
```

**It is not a policy gate and not a hardware condition.** It ensures a subsystem is
up before the download path uses it. In the normal case it returns 0 and the chain
continues.

## 4. Consequences

**Gate 1 is not a suspect for "EDL worked once".** Both of its success paths return
0, and the only non-zero return is a genuine initialisation failure - which would
log an error, and no such error appears in either boot log.

That leaves the earlier ranking intact and now better founded:

| gate | status |
|---|---|
| 1 | **not a gate** - a lazy initialiser, passes in every normal boot |
| 2 | passes deterministically: `skip_ddr_init_in_EDL = 0 < 2` |
| 3 | **the only gate whose state can differ**, and whose history is known |

`docs/60` said gate 1 was undecoded and could have been "a hardware condition, a
security state, or a policy flag". None of those is true. It is bookkeeping.

## 5. What remains, and it is narrow

The EDL decision now has exactly one variable left:

```
dload_entry_count  at 0x148F0080
```

- incremented on every entry into `boot_dload_entry`;
- compared against 2;
- the one working boot did **not** log the `> 1` message, so it was a first entry;
- it lives in the same `0x148Fxxxx` block as gate 1's flag, which a warm reset
  preserves and a cold boot re-initialises.

Everything else in the chain is either a constant on this board or a normal-path
initialiser. The goal therefore reduces to: **get the device to take the
first-entry path again**, which requires a genuine cold boot and no warm reset
before the attempt.

## 6. Honest limits

- `0x14857818` and `0x14855e28` (the initialisation work) were not read; the
  conclusion above does not depend on what they do, only on the return convention
  shown by the two `cbz`/`cbnz` tests.
- The two callback addresses `0x148C36B8` / `0x148C36F8` were not examined.
- "A warm reset preserves this block" is inferred from the block's address range
  and from the fact that a cold boot re-runs XBL from its entry point. It has not
  been tested by reading the block across both kinds of boot - which would need a
  HELLO, the standing blocker.
