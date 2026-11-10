# Escalation surfaces: what could still open this tablet

A deliberately broad survey of everything in the artefacts we hold that could
constitute a path. Written because pursuing one hypothesis at a time produced two
weeks of dead ends, while a systematic inventory takes one pass.

**Read this as a map of leads, not a list of capabilities.** Every entry still has
to be traced to the branch that acts on it. `17-write-gate.md` is the template for
what "traced" means: name → reference site → decoded condition → behaviour on each
outcome.

Reproduce with `scripts/capability_inventory.py`.

---

## 1. The strongest lead: forced EDL over the USB data lines

The devprg XBL contains a complete, named procedure for entering EDL by holding
the D+ line low — the principle every "EDL cable" implements:

```
0x148b5012  init_dp_gnd Failed
0x148b5025  qusb_dci_dp_gnd_check:
0x148b503d  dpGnd LOW, break
0x148b504e  dpGnd HIGH
0x148b5059  wait unplug(dpGnd LOW), (ms):
0x148b5077  dpGnd LOW, enter FEDL
0x148b508d  vioclt_eud_set
0x148b509c  qusb_dci_eud_init
```

Reading it as a procedure:

```
init_dp_gnd Failed              initialise the D+ pulldown
qusb_dci_dp_gnd_check:          poll the line
dpGnd LOW, break                a momentary LOW ends the wait
dpGnd HIGH                      line released
wait unplug(dpGnd LOW), (ms)    wait for it to be released
dpGnd LOW, enter FEDL           sustained LOW at boot -> forced emergency download
```

The same block exists in the Firehose image (`0x149d4534`–`0x149d45b9`), so this
is not a devprg-only path.

### The trigger parameters, read from the code

`fedl_timing.py` and the disassembly of the check routine give the numbers:

```
0x14882e78  entry of the check routine
0x14882ea8  movz w0, #0x14          settle delay, 20 ms
0x14882eac  bl   0x148829bc        udelay(20)
0x14882eb0  bl   0x14882e10        init_dp_gnd (retries 3x with '0x52/0xb1')
0x14882eb8  b.eq 0x14882ef4        init failed -> give up
0x14882ec4  movz w21, #0x3e8       1000 poll iterations
0x14882ebc  movz w23, #0x3028
0x14882ec8  movk w23, #0x88e, lsl #16   -> 0x088E3028   PHY register
```

So the poll loop is **1000 iterations**, each with a delay, against a USB PHY
register at `0x088E3028`. The practical window is on the order of **tens of
seconds**, not milliseconds — which is the opposite of what the earlier note
assumed when it described the cable as unreliable.

That single fact changes the experiment: a failure before was very likely a
**setup** failure, not a timing failure.

**Why this matters more than anything else in this document.** `FEDL`
(*forced emergency download*) is a boot-ROM-level path. It does not need the
Firehose programmer to start — which is exactly the thing that fails today. And
the trigger is on the USB connector, not on the mainboard, so it needs no
disassembly.

Note what the existing notes say about the EDL cable attempt
(`07-dead-ends.md` §D1): it "worked **once**", producing a genuine
`HELLO ver=3 mode=0` from PBL, and was unreliable afterwards. That is consistent
with a contact/timing problem in the cable or the attempt, not with the path being
absent. The code above says the path exists.

**What to determine next, all offline:**

- the polling interval and the required LOW duration (`wait unplug(...), (ms)`)
- whether the LOW must be present at power-on or is latched afterwards
- whether `vioclt_eud_set` / `qusb_dci_eud_init` is the same trigger or a second one

---

## 2. EUD: a debug path that bypasses Firehose entirely

```
0x148ac31f  EUD Init
0x148bba6c  EUD wait %ds
0x148bba79  EUD %d
0x148aec9d  boot_eud.c
0x148b4dee  usb_eud_is_active, status
0x148b4e84  usb_eud_serial
0x148b508d  vioclt_eud_set
0x148b509c  qusb_dci_eud_init
```

`EUD` is Qualcomm's Embedded USB Debug. It is a **transport**, not a storage
protocol, and it is normally gated by debug policy — but the presence of the whole
init sequence in the boot path, with a timeout string (`EUD wait %ds`), means the
code is compiled in and reachable under some condition.

Worth checking: what makes `usb_eud_is_active` true. If it depends on the debug
policy below, these two leads combine.

---

## 3. Debug policy: the gate on all of the above

```
0x148ad48b  debug board connected
0x148b2196  debug policy applied
0x148b21ab  no debug policy applied
0x148ad011  max-dbg-board-id
0x148ad022  min-dbg-board-id
0x148aed23  boot_dbginfo.c
```

This is the standard Qualcomm mechanism: a signed debug policy image can enable
JTAG/EUD and relax checks, and it is accepted only for board IDs in a declared
range. The two range properties are interesting because they describe **which
boards a policy may be applied to**, and a range is a condition that can be
satisfied or not.

Two questions, both answerable by reading code:

- where is the policy read from (a partition? a fuse? an image in the boot chain?)
- what exactly does `applied` unlock

---

## 4. Fuses are written here, and the code says so

```
0x148b0902  Unable to write to TCSR Wonce register, value written=0x%X, value read=0x%X.
0x148b211e  Static Fuse Overwrite
0x148b1c1d  DDR: Checksum on flash is %d
```

`Static Fuse Overwrite` and a TCSR "Wonce" (write-once) register appear in the
boot path. Writing a write-once register is the one operation that would *reduce*
future options, so this is recorded primarily as a **hazard**: any experiment that
touches fuse code must be understood before it runs.

It is also a genuine lead — a fuse that is written from software is a state that
was set by something.

---

## 5. A memory-write primitive that is not the storage write path

```
0x148b3d6a  DDI: ddr write command
0x148b3fc8   write:addr=0x%016lx
0x148b3ffa  (neighbouring region)
0x149ce507  size in bytes is %d, nothing to peek/poke
0x149ce3e6  program
```

`DDI: ddr write command` with an address argument is a memory-level write in the
boot environment. `peek`/`poke` in Firehose are XML verbs that modify memory
directly and are **not** part of the `lenovolock` gate (only `program` and `erase`
consult it — measured, `17-write-gate.md` §5).

If the programmer ever reaches its XML listener, `poke` is the most powerful verb
available with no lock check. That does not help today, but it means the value of
"get Firehose up" is higher than "we could flash": it also grants arbitrary memory
write, which is how a running system is redirected.

---

## 6. Deprecated and partially-removed paths

```
0x149cea18  patch command is deprecated%c
0x149cea73  patch size too large %d
0x149ce42b  firmwarewrite
```

`patch` is still dispatched but reports deprecation; `firmwarewrite` is a distinct
verb from `program`. Deprecated code that is still reachable is a classic source of
missing checks, and it is not gated by `lenovolock` on the evidence so far
(only `program` and `erase` were traced to the gate).

---

## 7. Ranked by what would actually help

| # | Path | Why it could work | Cost to test |
|---|---|---|---|
| 1 | **Forced EDL via D+ low** | boot-ROM level; does not need the failing programmer; connector-only | a cable and correct timing |
| 2 | Debug policy | would enable EUD/JTAG and relax checks | code reading first |
| 3 | EUD | bypasses the XML listener entirely | needs policy, probably |
| 4 | `poke` once Firehose runs | unGated memory write | needs Firehose |
| 5 | `patch` / `firmwarewrite` | possibly unGated | needs Firehose |
| 6 | Fuse write | state that was set can be examined | high risk, investigate only |

---

## 8. What this document deliberately does not claim

- That forced EDL will work **on this unit**. The code path exists; whether the
  hardware presents D+ in a way that a cable can hold low depends on the connector
  wiring, and that is not in any file we hold.
- That any of these bypasses secure boot. `FEDL` gets you a PBL session; the
  programmer still has to authenticate, as documented in `06-signing.md`.
- That the previous EDL-cable attempt was set up correctly. It worked once, which
  argues the path is real and the setup was unreliable.

The honest summary: **the EDL cable is the one lead that does not depend on the
programmer starting, does not need the case opened, and whose mechanism is
confirmed present in code.** It deserves to be re-attempted properly before
anything else.
