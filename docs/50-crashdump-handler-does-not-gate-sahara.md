# The crash-dump handler does not gate Sahara — the "re-enter" lead is closed

`docs/35` left one question open: why does a 900E node enumerate and then emit no
HELLO, when the same node delivered a full `HELLO_REQ` earlier the same day.

A plausible candidate was found in the strings of `XblRamdump.elf` - the crash-dump
handler itself, i.e. the code that runs in exactly this state:

```
0x81ad4388   "re-enter ramdump"
0x81ad4871   "Sahara Init"
0x81ad487d   "Sahara Open"
```

If the handler could "re-enter ramdump" as a retry path, it might skip `Sahara
Init` and never emit a HELLO. That would explain the observation completely.

**It does not. The lead is closed.**

---

    20|## 1. What `re-enter ramdump` actually is

Its only caller is `0x81a4378c`, inside a loop:

```
0x81a4376c  ldrh w8, [x29, #-0x14]     a counter
0x81a43770  add  w8, w8, #0x1
0x81a43774  strh w8, [x29, #-0x14]     increment it
0x81a43778  b    0x81a43110            loop back

0x81a43788  b    0x81a437b8            skip the re-enter body entirely
0x81a4378c  adrp x0, 0x81ad4000
0x81a43790  add  x0, x0, #0x388        "re-enter ramdump"
0x81a43794  bl   0x81a4b050            log it
0x81a43798  adrp x8, 0x81b1d000
0x81a437a0  ldr  x0, [x8]
0x81a437a4  bl   0x81a42280            (dump step)
0x81a437b0  bl   0x81a42dd0            (dump step)
0x81a437b4  b    0x81a437b8
0x81a437b8  ldrh w8, [x29, #-0xc]      a status word
0x81a437bc  cbz  w8, 0x81a437e4        zero -> return
```

That is a **retry iteration of the dump loop**, with a counter and a status word.
It logs, repeats two dump steps, and returns. Nothing here touches Sahara state.

## 2. Where `Sahara Init` sits

`0x81ad4871` `"Sahara Init"` is referenced once, from `0x81a47090`, which is in a
different function that also logs `"HFAT Dump Init"` (`0x81ad4685`) and calls
`0x81a43800`.

`0x81a43800` turns out to be a **variadic logger**: its prologue spills `w0..w7`
to `[sp,#1..#8]` and `x0..x7` to `[sp,#0x98..#0xc8]`, which is the standard
`va_list` capture shape. So `Sahara Init` there is a *message being logged*, not a
branch being taken.

## 3. Conclusion

```
"re-enter ramdump"  =  a dump-loop iteration, not a mode change
"Sahara Init"       =  a log string in the dump path
```

There is no conditional in the crash-dump handler that chooses "skip Sahara".
So the explanation for the missing HELLO is **not** that the handler retries into
a Sahara-less state.

That leaves `docs/35`'s reading standing: the node enumerates and stays silent,
most consistently because the firmware stage that emits the HELLO does not run -
which matches the watchdog-collected boot (`RST_STAT = 0x3`, `docs/15` §5) and the
16 s absence that ends in a reset rather than a fresh session.

## 4. Method note, and a tool addition

The handler is a standalone ELF (`XblRamdump.elf`), not a melf inner image, and
`a64.py` could only read melf images. That blocked reading the one file that
describes the state the tablet is actually stuck in. `a64.py` now takes `--elf` and
parses the file's own program headers:

```
python scripts/a64.py --elf <ROM>/image/XblRamdump.elf --offset 0x4750 --count 40
```

Three offsets were wrong before the segment arithmetic was applied per file
(two in the melf, one here), each producing a coherent listing of unrelated code.
The habit that catches it: check the first listing against something already known
about that address before trusting the rest.
