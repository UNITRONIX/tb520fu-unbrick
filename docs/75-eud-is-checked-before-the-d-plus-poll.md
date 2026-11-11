# EUD is checked by XBL in four places, including the forced-EDL path

`docs/74` established that the EUD node exists and is enabled in the Android DTB. This
document records where the boot chain actually consults it, which is what decides
whether route C is reachable before Android runs.

---

## 1. The function and its callers

`usb_eud_is_active` (`0x1488254c`) reads bit 0 of `0x088E2000` - the region the live DT
names `eud_mode_mgr2` (`docs/74`). Complete caller list in image[2]:

```
0x14879650
0x14879820
0x148798fc
0x14882ddc
```

**`0x14879650` is inside the forced-EDL function** that `docs\49` decoded:

```
0x14879648  movz w19, #0x1
0x1487964c  ...
0x14879650  bl   0x1488254c        <- EUD check
0x14879654  tst  w0, #0xff
0x14879658  b.eq 0x14879698        EUD not active -> the D+ poll path
```

So the two entry mechanisms are **not independent branches** - the forced-download
function asks EUD first, and only falls through to the D+ poll when EUD is inactive.

That is a materially different picture from `docs/42`, which treated FEDL and EUD as
alternative routes. In the code they are **ordered**: **EUD first, D+ poll second.**

## 2. What that means for the goal

If bit 0 of `0x088E2000` is set, XBL:
- skips the D+ poll entirely (`b.eq` not taken),
- and proceeds down the path that leads to `enter forced EDL`.

So making EUD active would give the goal **without a hardware short at all**.

And `docs/74` showed the Android DTB declares the node with `status = "okay"` and
`qcom,secure-eud-en` present. The question is therefore not "is EUD supported" but
**"is secure EUD permitted on this unit's fuse state"** - which is a different
question and not answerable from the DTBs we hold.

## 3. What the other three call sites suggest

`0x14879820` and `0x148798fc` sit in PHY configuration code (`docs\74` §1's neighbours) -
they are the USB controller setting up in response to the EUD state, not deciding the
boot mode. `0x14882ddc` is in the same PHY region.

So the decision point is effectively **`0x14879650`**, and the rest are consumers.

## 4. The honest status of route C, corrected again

| question | answer | evidence |
|---|---|---|
| is EUD declared? | yes, `status = okay` | live DT, `docs/74` |
| does XBL consult it? | yes, before the D+ poll | this document |
| does the boot DTB configure it? | no | `docs/74` |
| is it permitted on this unit? | **unknown** | needs fuse/secure-state knowledge |
| was it ever observed working? | **no** | nothing tested |

Route C is now **the most attractive of the remaining options**, for a specific
reason: it is checked *inside* the same function as route B, *before* route B's
condition, and it needs no physical contact if the secure flag permits it.

## 5. What would settle it

One observation, and it is the same one the whole session has been blocked on - but it
can be attempted with less risk than a short:

1. try the normal power-on and read the XBL log for the line
   `usb: qusb_dci_eud_init` (present in both captured logs, `docs\56`) and for any
   `usb_eud_is_active` status value;
2. the captured logs already contain `usb: qusb_dci_eud_init` - so **EUD
   initialisation runs**. What has never been captured is the *result* of
   `usb_eud_is_active`.

So a targeted measurement exists: **read bit 0 of `0x088E2000`**. It is in the
`0x088E2xxx` block, and `docs\45` §4 recorded that `0x088E2000` kills a 900E session
when read directly - the same way the TCSR register does. That is why it has never been
read.

## 6. Status of the goal

Unchanged: `HELLO ver=3 mode=0` not obtained. But the ranking has shifted twice today
on the strength of files that were already on disk:

```
before docs/74   route C closed - "undeclared"
after  docs/74   route C open   - declared and enabled
after this doc   route C is checked BEFORE route B's condition, in the same function
```

**EUD is now the first thing to understand, not the last.**
