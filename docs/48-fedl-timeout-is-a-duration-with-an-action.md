# Session log: the FEDL timeout property is a duration with an action, not a poll

Recorded from this session's offline work, so the next session does not re-derive
it. This is the last open item from `docs/39`–`docs/42`.

---

    10|## 1. The three strings that settle it

Searching the XBL core for timeout-related property names returns a small set, and
three of them belong together:

```
0x08873c  /sw/boot/forced_download            the node
0x08adbd  /sw/boot/fedl_timeout                the timeout node
0x08adf4  DTB: couldn't retrieve fedl timeout action setting
0x08ae27  EMERGENCY_DLOAD_TIMEOUT_COOKIE_SET: Powerdown
0x08ae55  EMERGENCY_DLOAD_TIMEOUT_COOKIE_SET: Reset
```

The DCB declares, for this board:

```
/sw/boot/fedl_timeout/ver     = 1
/sw/boot/fedl_timeout/action  = 1
/sw/boot/forced_download/check_dp_timeout = 0x2710    (10000)
```

So `check_dp_timeout` is a **duration in an emergency-download timeout**, and
`fedl_timeout/action` selects what happens when it expires: **power down** or
**reset**. `action = 1` selects one of the two.

That is a coherent mechanism and it is not a poll of the D+ line:

```
short detected -> EDL entered -> programmer uploads -> if nothing happens
within <timeout>, then powerdown-or-reset per fedl_timeout/action
```

This fits `docs/41` §4, which showed the entry check itself is a single masked
read with no duration. The two stages are separate, and `docs/18`'s "~50 ms poll of
the PHY" was describing neither of them.

## 2. The consumer, located

The `forced_download` node path is referenced from eight sites; the first two are
the ones that read the sub-properties:

```
0x148302c0  -> 0x148ac73c   "/sw/boot/forced_download"
0x14830304  -> 0x148ac755   a sub-property
0x14830458  -> 0x148ac75a   another
0x14830e54  -> 0x148ac76f
0x14831e58  -> 0x148ac7a2
0x14831f20  -> 0x148ac7b5
0x14831f8c  -> 0x148ac7ae
0x14833838  -> 0x148ac7f3
```

`0x148302c0` is inside the same function that `docs/16` §4.3 identified as reading
`skip_ddr_init_in_EDL` (`0x14831244`) — i.e. the boot configuration reader. So the
forced-download settings are consumed in the ordinary property pass, not in a
specialised path.

The disassembly around `0x1482f2c0` shows the standard shape: load a node handle,
call through `[x8+0x18]` and `[x8+0x20]`, then branch on the result. The
sub-property names are resolved by the node, which is why a plain string search for
`check_dp_timeout` finds nothing — the name is looked up inside the DTB at runtime,
not held as a literal in the image.

**Consequence for further reading:** no amount of string searching will produce the
`check_dp_timeout` consumer. It has to be traced from the property-id map, which
means either decoding the DTB node lookup or reading the function's argument setup.
That is a bounded task, and it is recorded here as the entry point rather than
attempted speculatively.

## 3. State of the goal at the end of this session

Verified against the device, not remembered:

```
tablet.py selftest, run twice
  VID_05C6 enumeration      PASS   1 node (PID_900E)
  Qualcomm COM port         PASS   COM10
  bytes pending             FAIL   0   <- the HELLO is still absent
  memory table cached       FAIL
  programmer on disk        PASS   1 569 028 B
```

and immediately after a power cycle, with the device back on the bus for 26 s:

```
port COM10
bytes pending: 0
```

So the central blocker is unchanged and re-confirmed on a fresh boot: **the 900E
node emits no HELLO**, and therefore route A (bump to 9008) cannot be executed.

## 4. What this session added to the picture

Four findings, all from files already on disk:

| finding | document |
|---|---|
| the dump order is by declared size, not address, so `DDR_DATA` was never blocked | `33` |
| the HELLO is first-opener-wins, and our own `SAHARA_RESET` was killing the port | `34` |
| DDR training describes all eight 2 GiB windows, so DRAM is not the fault | `36` |
| the 40 MiB boundary is the start of `qdss_region`, not a DRAM limit | `46` |

and three that sharpen the hardware routes:

| finding | document |
|---|---|
| FEDL entry is `(status & 0x30000) == 0x10000`, one bit, no duration | `41` |
| EUD entry is bit 0 of `0x088E2000`, and no DTB switch enables it | `42` |
| Volume Up is PM8550 gpio6 (needs a driver); Power and Volume Down are PON | `47` |

Taken together, nothing in this repository now indicates a hardware fault. The
remaining blocker is that the firmware stage which emits the HELLO does not run,
which is consistent with the watchdog-collected boot recorded in `docs/35`.
