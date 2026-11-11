# The three routes to a PBL-level EDL session, ranked by what actually blocks them

Goal: `HELLO ver=3 mode=0`. Three mechanisms exist in this device's firmware. Each
is blocked by a different thing, and that difference is what decides what to do
next.

---

## Route A — bump 900E → 9008

    10|**Mechanism:** Sahara mode switch, then `SWITCH_MODE(0)` and a `DONE`.
Documented in `docs/14`, worked twice, sequence never in question.

**Blocker:** the 900E node no longer emits a HELLO at all. Verified with a single
handle held across a full power cycle, zero writes, 100+ s of reading
(`docs/35`). A spent HELLO is gone; `SAHARA_RESET` does not produce another
(`docs/34`).

**What would unblock it:** a real cold boot that re-runs the firmware path which
emits the packet. Untested variant: leave the device off long enough for the
RTC/always-on domain to lose state. Every cycle so far was a key-hold reset.

**Cost:** free. **Requires:** the owner, a few minutes.

---

## Route B — FEDL by hardware short (D+ to ground)

    30|**Mechanism:** stage `boot_fedl_check` (`0x14843a7c`) runs **before**
`sbl1_ddr_init` in the XBL stage table, so it does not have to pass through the
stage where the programmer dies (`docs/40`).

**The condition, reduced to one bit** (`docs/41`):

```
0x14850a98   read the USB status word (0x221C8604, or a RAM cache)
0x148509e0   and  w8, w0, #0x30000
0x148509e4   cmp  w8, #0x10000
0x148509e8   csinc w0, wzr, wzr, eq
```

FEDL is requested when bits 17:16 == `01`. `10` is explicitly rejected, so this
is one encoded state, not any USB activity. **There is no duration in this check**
— `check_dp_timeout = 10000` belongs to the *next* stage, so `docs/18`'s "~50 ms
window" was measuring the wrong thing.

**Blocker:** the bit must already be latched when stage 1 reads it, which means
the short must be present **before the PHY initialises** — before and during
power-on, not after. And no verified pin-out for this tablet's Type-C receptacle
exists in any document here.

**What would unblock it:** the pin-out, then one attempt with the short applied
before power.

**Cost:** free-to-cheap. **Requires:** a cable or a probe, and the pin-out.

---

## Route C — EUD (Embedded USB Debug)

**Mechanism:** a separate transport, not the Sahara listener at all. If it comes
up, it does not care whether Firehose ever binds.

**The condition, also one bit** — newly located this session:

```
0x1488254c  stp x29, x30, [sp, #-0x10]!
0x14882554  movz w8, #0x2000
0x14882558  movk w8, #0x88e, lsl #16      w8 = 0x088E2000
0x1488255c  ldrh w8, [x8, #0x0]           16-bit read of the USB PHY block
0x14882560  tbnz x8, #0, 0x1488256c       bit 0 set -> EUD path
0x14882564  mov  w0, wzr                  otherwise: inactive
```

and the same address appears again immediately after, read the same way, then
feeding `0x148825cc` which logs `usb_eud_is_active, status %d`.

So EUD activity is signalled by **bit 0 of `0x088E2000`**, and there is a second
consumer of the same bit one function later, which is what a real state flag
looks like rather than a one-off comparison.

Note the relationship to Route B: both decisions read the **same USB PHY block**
(`0x088E2xxx` for EUD, `0x221C86xx` for the FEDL status). They are two views of
one physical condition.

**Blocker:** unknown whether this unit can set that bit. `docs/18` §2 suggested it
is gated by debug policy, and the strings `debug policy applied` /
`no debug policy applied` / `max-dbg-board-id` / `min-dbg-board-id` exist in the
image — but **no `eud` node exists in either device DTB** (searched the DCB, 1258
properties, and the pre-DDR DTB, 3135 properties, for `eud`, `debug`, `jtag`:
zero hits).

That absence is itself a finding: there is no device-tree switch to flip. Whatever
enables EUD is not a property this board declares, which makes it either a fuse /
debug-policy artefact or something the hardware does on its own.

**Cost:** unknown. **Requires:** probably the case, if it needs a debug policy.

---

## What is worth doing next, in order

    110|1. **Route A with a proper discharge.** Free, needs only the owner, and it is
   the only untested variant of the cheapest route. Every prior attempt was a
   key-hold reset.
2. **Route B once the pin-out is known.** The condition is one bit and the check
   has no timing window; the only unknown is which pads.
3. **Route C last.** No device-tree switch exists, so it likely needs a debug
   policy, which is a bigger step.

## Evidence status

| claim | status |
|---|---|
| FEDL runs before DDR init | **measured** — stage table order |
| FEDL condition is bits 17:16 == `01` | **measured** — disassembly, offset verified against a known predicate |
| FEDL check has no duration | **measured** — it is a single read and compare |
| EUD condition is bit 0 of `0x088E2000` | **measured** — disassembly |
| no `eud` property exists in either DTB | **measured** — 4 393 properties searched |
| a short before power-on sets the bit | **NOT tested** |
| EUD can be enabled on this unit | **NOT tested, likely needs debug policy** |
| a discharge restores the HELLO | **NOT tested** |
