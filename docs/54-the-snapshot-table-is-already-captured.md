# The crash dump already contains the snapshot table, with the HWID in it

`docs/53` found that `CD_STRCT` is live ARM64 which, before halting, stores three
USB-PHY halfwords into a fixed table at `0x800DF408`–`0x800DF414`, and noted that
the table sits inside the already-captured `DDRCS0_0` window.

**That dump is on disk.** The table can be read now, without touching the device.

    10|---

## 1. The dump really is the same code

`com_attempt/DDRCS0_0_first40MB.bin`, offset 0:

```
dump     0a 00 83 d2 0a 08 a6 f2 0a 10 1c d5 1f 20 03 d5 ...
CD_STRCT 0a 00 83 d2 0a 08 a6 f2 0a 10 1c d5 1f 20 03 d5 ...
```

Bit-identical for the first 64 bytes and beyond. So the region the crash dump
labels `CD_STRCT` is `0x80000000` in this capture, and the table the code writes to
is directly addressable as `offset = VA - 0x80000000`.

## 2. The table, decoded

The code stores a **halfword** into each slot, and the instructions name the
source:

| address | value | written from |
|---|---|---|
| `0x800DF408` | `0x80E1` | `[0x221C8744]` |
| `0x800DF40A` | `0x2022` | — not written by this routine |
| `0x800DF40C` | `0x0040` | `[0x221C8700]` |
| `0x800DF410` | `0x8AA5` | `[0x221C8610]` |

Read as 32-bit words the slots look like this:

```
0x800DF408  0x202280E1
0x800DF40C  0x00000040
0x800DF410  0x147D8AA5
```

## 3. The value that matters

`0x202280E1` splits into `0x2022` (high) and **`0x2280E1`** (low).

**`0x2280E1` is this tablet's HWID** — the value recorded independently in
`docs/03` and `docs/14`, and the one a Sahara `MSM_HW_ID_READ` would return.

Two readings are possible and they must not be confused:

- **(a)** `0x800DF408` really holds `0x2280E1` and the neighbouring `0x2022` is a
  separate halfword written by different code; or
- **(b)** the 32-bit value `0x202280E1` is a single datum that happens to contain
  `2280E1`.

The instruction at `0x800000c8` is `adr x9, 0x800df408` followed by `strh`, which
stores **16 bits**. That favours (a): the slot at `0x800DF408` receives `0x80E1`
and the `0x2022` above it was written elsewhere. But `0x80E1` on its own is not
`0x2280E1`, so either the full word was written by two instructions I have not
matched, or the coincidence is partial.

**This is stated as unresolved on purpose.** The alignment is suggestive and not
established, and an earlier version of this project already drew a conclusion from
a value that appeared in a listing without being traced to an instruction.

## 4. What is solid regardless of that

- The table exists, at known addresses, inside a dump we already hold.
- Three halfwords in it come from `0x221C86xx` / `0x221C87xx` — the block that
  decides FEDL transport and carries the D+ latch (`docs/41`).
- `0x800DF410 = 0x8AA5` and `0x800DF40C = 0x0040` are therefore the device's own
  record of two PHY halfwords at crash time.

Those two are the values worth interpreting next, because their addresses map to
the FEDL decision inputs. `0x0040` at `[0x221C8700]` and `0x8AA5` at
`[0x221C8610]` can be checked against what `docs/41` predicts for each branch.

## 5. Next step, and it is cheap

Read the same three addresses from a **second** dump, or from a live session, and
compare. A value that changes between boots is a state flag; one that is constant
is a configuration or a constant table. That distinction is what decides whether
this table records the crash condition or just echoes fixed PHY settings.

The second dump does not exist yet, and a live read still needs a fresh HELLO -
the same blocker as the rest of the session. But this is now a **three-halfword
comparison**, not a speculative decode.
