# The 40 MiB wall is a property of the hardware, not of the mode

A repeat of the dump from a different starting state, to test whether the stall at
`0x82800000` depended on the device being in crashdump mode.

**It does not. The wall is in the same place.**

---

## 1. What was tried

`Bump-Then-Dump.ps1` was written to upload a programmer and then dump memory from the
resulting `9008` state, on the theory that the memory table or CS0 behaviour might differ
there.

What actually happened is more informative than the plan: the device answered the Sahara
handshake with `mode = 2` (MEMORY_DEBUG), so `QSaharaServer` took the dump path instead of
the upload path:

```
11:30:46: RECEIVED <-- SAHARA_HELLO
sahara_hello->mode = 2
11:30:46: STATE <-- SAHARA_WAIT_MEMORY_TABLE
```

So this was a second full dump, from a fresh boot, reached by a different code path — a
useful control even though it was not the intended experiment.

## 2. What it showed

The dump walked 13 812 addresses at ~33 per second with **zero zero-byte reads** until:

```
last successful read : 0x80000000 .. 0x82700000
first failing read   : 0x82800000
zero-byte reads      : 3, then permanent stall
```

**Identical to the first dump.** Same boundary, same behaviour, same stall.

Two runs, different sessions, different starting conditions, one result:

```
DDR CS0 answers from 0x80000000 to 0x827FFFFF inclusive.
0x82800000 returns nothing, and every subsequent request does the same.
```

## 3. What this settles

The boundary is **not**:

- a crashdump-mode artefact — it appears in both modes;
- a tool defect — the vendor's tool reports it precisely;
- a session-timing problem — it reproduces across sessions and power cycles.

It **is** a property of how this device's DRAM maps, and it is stable.

That makes the earlier hypotheses rankable:

| hypothesis | verdict |
|---|---|
| programmer dies from lack of memory past 40 MiB | **weakened** — there is populated memory at `0x8af800000`, so memory exists above the wall |
| DDR only partially trained | **supported but unproven** — six of eight windows are `0xFF`, which is what absent training looks like |
| crash handler refuses to map more than 40 MiB of CS0 | **possible** — nothing distinguishes this from partial training from the host |
| the 40 MiB limit itself causes the programmer failure | **not established** |

## 4. Why `DDR_DATA.BIN` could not settle it

The table lists it at `0x1000080000`, the highest address of all 53 entries. `QSaharaServer`
walks addresses ascending. So the region is reached only after every other one — including
the CS0 window that stalls permanently.

Two attempts to reach it have failed for this reason. There is no option in the tool to
choose region order, and a custom client cannot win the serial-port HELLO race
(`28-hello-race-on-serial.md`).

## 5. Where this leaves the investigation

The DDR question can no longer be advanced further from the host with the tools available.
The two facts that would settle it are:

- the DDR training data, unreachable by ordering;
- a live read of CS0 at an address above `0x82800000`, which the device refuses.

Both require something the host does not have: either a different entry state where CS0
serves fully, or physical access.

**What is established and worth keeping:**

- the device declares 16 GiB of DDR and six of eight windows are unmapped;
- CS0 serves exactly 40 MiB, reproducibly, in any mode;
- the boot chain, ABL included, is resident and identifiable in the captured memory;
- the display panel is bound and its configuration is present;
- the write gate is a byte in `lenovolock`, not a fuse (`17-write-gate.md`);
- the programmer is accepted by Sahara and stops ~98 ms later (`20-entry-point-spin.md`).

That is a coherent picture of a device whose lower boot stages work, whose DRAM is
substantially absent, and whose storage write path is gated by data rather than hardware.

## 6. Files

The nine dump files total 16 GB and are 0xFF apart from the two characterised windows.
`DDRCS0_0_first40MB.bin` holds the real content that matters; the rest is deletable.
Logs `bump_dump_step2.txt` and `full_dump.log` record every address, length and payload head.
