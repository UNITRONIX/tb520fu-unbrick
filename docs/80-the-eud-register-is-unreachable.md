# The EUD register is outside every exposed region — the loop is confirmed closed

`docs/76` said the EUD route closes into a loop. That was reasoning. This is the
measurement, and it is the last thing that could be checked about route C without the
device.

---

## 1. The region check

The EUD status bit is at `0x088E2000` (`docs\41`, `docs\74`). Checking it against every
region the crash-dump handler serves:

```
region      base            size            contains 0x088E2000?
OCIMEM      0x0014680000    0x0002C000      no
CODERAM     0x000B000000    0x00018000      no
DATARAM     0x000B0E0000    0x00008000      no
DCC_SRAM    0x0010080000    0x00018000      no
CPUCPFW     0x0017D00000    0x00010000      no
DDRCS0      0x0080000000    0x80000000      no  (starts above it)
```

`0x088E2000` is in the `0x08000000`–`0x0FFFFFFF` range, **below** DDRCS0, and it belongs
to none of the nine regions the handler publishes.

**So the EUD status cannot be read, by any means the crash dump offers.**

## 2. Why it also cannot be read the other way

`docs\45` §4 recorded that reading `0x088E2000` **terminates a 900E session**. So the two
routes that exist for reading a register both fail:

| method | outcome |
|---|---|
| through the published region table | not in it |
| by direct address (the `ddr_peek` style) | kills the session |

That is the same wall the TCSR register `0x1FD9000` presents, and it is consistent: both
are always-on blocks the crash handler does not map.

## 3. What the loop looks like now, with every link measured

```
to use route C        need bit 0 of 0x088E2000 set
to set it             need secure-EUD permission (fuse state, unreadable)
to check permission   need to read 0x088E2000
to read it            need a Sahara session
to get a session      need the goal
```

Every one of those steps is now supported by a specific document rather than by
supposition:

| link | evidence |
|---|---|
| bit 0 is the flag | `docs\41` disassembly, `docs\74` DT node name |
| it is checked before the D+ poll | `docs\75` |
| it is not in any exposed region | this document |
| direct read kills the session | `docs\45` §4 |
| a session needs the goal | `docs\34`, `docs\35` |

## 4. The same structure for the other routes

For completeness, the same four-link check on every route:

| route | first link | measured blocker |
|---|---|---|
| cookie → `boot_dload_entry` | need bit 12 of `0x1FD9000` | nothing readable sets it (`docs\70`, `docs\71`) |
| bump 900E → 9008 | need a fresh HELLO | node emits none (`docs\35`) |
| EUD | need bit 0 of `0x088E2000` | unreadable and unsettable (this document) |
| **FEDL by short** | need the D+ latch set before boot | **needs a pin-out, which is not in any file** |

Three routes fail on a register that cannot be touched. **The fourth fails on a piece of
physical knowledge.**

That is the whole finding of this session reduced to one table.

## 5. Status

Goal `HELLO ver=3 mode=0`: **not achieved.** Verified state unchanged - `900E` present,
`COM10` open, no HELLO at any baud rate.

The offline analysis has now checked the last item that could be checked. What remains is
one of two things, and neither is a document:

1. **a Type-C pin-out for this model** - to attempt the FEDL short, the only route whose
   blocker is physical rather than a locked register;
2. **a genuine cold boot** - which is the only way to reset `dload_entry_count` and give
   the bump route one more chance, and which costs nothing to try.

Everything else has been read, measured, or shown to be unreadable.
