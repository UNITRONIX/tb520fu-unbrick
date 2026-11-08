# The Sahara protocol, as measured on this device

This is not a restatement of the Qualcomm specification. It is what this specific
PBL actually did, packet by packet, including the two bugs in our own code that
cost the most time and the vendor behaviour that is not in any specification.

Everything marked **measured** has a corresponding log line in
[`session-notes/`](../session-notes/). Everything marked **inferred** is reasoning
from code or strings.

---

## 1. Transport

| Property | Value |
|---|---|
| VID:PID (EDL) | `05C6:9008` |
| VID:PID (crashdump) | `05C6:900E` |
| Interface | 1 interface, `class=0xff subclass=0xff proto=0x11` |
| Endpoints | `0x81` IN, `0x01` OUT |
| `maxPacketSize` | 512 |
| Max payload seen | 1 048 576 B per request |

The `proto=0x11` value is the give-away that a programmer is running: it is the
Firehose profile. Its presence on `9008` means the programmer is bound to USB.

> **Note.** `edlclient`'s high-level `usb_class` helper failed on this host with
> `Permission denied`, while raw `usb.core.find()` + `set_configuration(1)` +
> `claim_interface(0)` worked. If you build on top of an existing library and it
> fails to open the device, try the raw path before concluding the device is at
> fault.

---

## 2. Packet format

All fields little-endian, 32-bit unless stated.

```
uint32  command
uint32  length        // total packet length, including this 8-byte header
byte[]  payload       // length - 8 bytes
```

The critical consequence, and the source of the worst bug in the whole effort:

> **A single `read()` on the bulk endpoint can return several packets
> concatenated, or a partial packet.** You must buffer the stream and consume
> exactly `length` bytes per packet, not assume one `read()` equals one packet.

Early scripts did `read(0x10000)` and parsed only the first header, silently
discarding the remainder. The device then answered requests we had already
mis-framed, and every subsequent exchange was off by an unknown number of
packets. This presented as `0xD` (`NAK_READ_DATA_ERROR`) — a transport error that
looked like a device fault.

The fix, in `scripts/sahara_upload.py`, is a `Link` class holding a `buf`:

```python
def read_packet(self, timeout_ms=5000, retries=3):
    while len(self.buf) < 8:          # accumulate a header
        self.buf += self._fill(...)   # never assume one read == one packet
    cmd, ln = struct.unpack_from("<II", self.buf, 0)
    while len(self.buf) < ln:          # accumulate the full body
        self.buf += self._fill(...)
    pkt, self.buf = self.buf[:ln], self.buf[ln:]
    return pkt
```

---

## 3. Commands observed

| Value | Name | Direction | Observed |
|---|---|---|---|
| `0x01` | `HELLO_REQ` | device → host | yes, both `mode=0` and `mode=2` |
| `0x02` | `HELLO_RSP` | host → device | sent by us |
| `0x03` | `READ_DATA` | device → host | yes, 37 times per full upload |
| `0x04` | `END_TRANSFER` | device → host | yes, with status |
| `0x05` | `DONE_REQ` | host → device | sent by us |
| `0x06` | `DONE_RSP` | device → host | yes |
| `0x07` | `SAHARA_RESET` | host → device | yes, works |
| `0x08` | `RESET_RSP` | device → host | yes |
| `0x12` | `64BIT_MEMORY_READ_DATA` | device → host | not used by this device |
| `0x13` | `RESET_STATE_MACHINE` | host → device | **never send — kills the pipe** |

### `0x13` versus `0x07`

Several early scripts used `RESET_STATE_MACHINE` (`0x13`) as a neutral "reset
before retry". It does not reset; it terminates the session in a way that leaves
the endpoint unusable, so the *next* attempt had nothing to talk to. A long series
of failures was caused by our own reset call.

`SAHARA_RESET` (`0x07`) is the correct call. The device answers `RESET_RSP`
(`0x08`) and presents a fresh `HELLO`.

---

## 4. The `HELLO` modes

The device sends `HELLO` with a `mode` field, and the mode changes what the
protocol means. This distinction is not obvious and matters a great deal:

| `mode` | Meaning | Observed when |
|---|---|---|
| `0` | `SAHARA_MODE_IMAGE_TX_PENDING` | genuine EDL, from PBL |
| `1` | `SAHARA_MODE_IMAGE_TX_COMPLETE` | after a completed transfer |
| `2` | `SAHARA_MODE_MEMORY_DEBUG` | crashdump — the "image" is a RAM dump request, not a programmer load |
| `3` | `SAHARA_MODE_COMMAND` | intermediate state during a mode switch |

`HELLO ver=3 mode=0` is what you want: a clean EDL session straight from PBL.

`HELLO ver=2 mode=2` is crashdump. It is *usable* — the mode-switch sequence
converts it — but be aware that in this mode the device will acknowledge a
**zero-byte** transfer as success. See §7.

Getting from `mode=2` to `mode=0` is a procedure in its own right, with its own
pitfalls and a 20-second re-enumeration. It is documented separately in
[`14-edl-mode-switch.md`](14-edl-mode-switch.md).

### Version

Both `ver=2` and `ver=3` appear. `ver=3` is used for the real transfer; `ver=2`
appears in crashdump and during mode switching. The `HELLO_RSP` must echo the
version the device asked for; sending 3 in reply to a 2 does not work.

---

## 5. The full upload sequence

As measured on a good session:

```
device:  HELLO_REQ   ver=3  mode=0
host:    HELLO_RSP   ver=3
device:  READ_DATA   image=0x0d  offset=0        len=...      ← image ID 13
host:    <data>
device:  READ_DATA   ...  offset=...             ...          ← ×37
host:    <data>
...
device:  END_TRANSFER  status=0x0  image=0x0d
host:    DONE_REQ
device:  DONE_RSP    cmd=0x06
```

**Numbers from the best observed run:**

| Quantity | Value |
|---|---|
| Total requested | 1 554 996 B |
| Full file size | 1 569 028 B |
| Never requested | 14 032 B (trailing padding) |
| `READ_DATA` packets | 37 |
| `high_water` offset reached | 1 569 028 B |
| `END` status | `0x0` |

The 14 032-byte gap is normal: the device requests only the images it needs, not
the file's trailing padding. Earlier notes flagged this as suspicious; it is not.
`high_water` covering the full file size is the correct health check, not
`bytes == len(file)`.

### Image ID

`image_id=0x0d` (13) is the "programmer" image class. Other IDs exist for
different payload kinds; this device only ever requested 13.

---

## 6. NAK codes actually seen

The published table runs `0x01`–`0x28`. The device returned codes **outside** that
range, which is the strongest single hint that its error reporting is vendor-extended.

| Code | Published meaning | Seen on this device |
|---|---|---|
| `0x0D` | `NAK_READ_DATA_ERROR` | yes — always a *symptom* of our framing bug |
| `0x21` | `HASH_TABLE_AUTH_FAILURE` | yes — when the melf blob was modified |
| `0x23` | `HASH_TABLE_NOT_FOUND` | yes — plain ELF with no hash segment |
| `0x29` | **not in the table** | yes — vendor NAK, returned after 64 bytes for ELF64 payloads |

### Reading `0x29` correctly

`0x29` is returned **after 64 bytes**. Sixty-four bytes is exactly the size of the
thing Sahara needs to decide what the payload is. So `0x29` is a decision made on
the *header*, before any hash table or certificate could be examined.

Interpretation: **format rejection, not a signature rejection.** This is the single
most consequential correction in the whole investigation, because it invalidated
several days spent on signing.

### Reading `0x21` correctly

`0x21` appeared when an image inside the melf was replaced. The transfer died at
byte **1 109 804**, and the replaced image begins at byte **1 117 008**.

The device therefore rejected the blob *before* reaching the modified image. That
proves the integrity check covers the container as a whole — not each image in
isolation. No per-image repair is possible.

### Reading `0x23` correctly

`0x23` (`HASH_TABLE_NOT_FOUND`) is what a plain ELF gets when it has no MBN hash
segment. This is the code that made `qtestsign` look promising: qtestsign adds
exactly that segment. It did not help, because `0x29` had already rejected the
payload 64 bytes in. See [`06-signing.md`](06-signing.md).

---

## 7. The zero-byte false success

Discovered by accident, and it invalidated a run that had been marked successful.

```
HELLO_REQ   ver=2 mode=2          ← crashdump
END_TRANSFER status=0x0  bytes=0/1569028   ← ZERO bytes transferred
DONE_RSP    cmd=0x06
```

In `mode=2` the device accepts an *empty* transfer and acknowledges `DONE`. A
script checking only `status == 0` reports success; nothing was uploaded.

**Mandatory check:** treat `END 0x0` as success only if
`bytes_transferred >= payload_size_actually_requested`. The `banner_capture.py`
script enforces `MIN_SENT = 1_554_996` for exactly this reason.

---

## 8. `DONE` is not optional

Hypothesis: maybe the programmer starts on `END` alone, and our `DONE` interferes.

Tested four variants:

| Variant | Behaviour after `END` | Device response |
|---|---|---|
| A | send `<nop/>`, no `DONE` | returns `END_TRANSFER status=0x0D` — treats the XML as a Sahara packet |
| A' | send `<configure/>`, no `DONE` | identical |
| C | send `SAHARA_EXECUTE` subcommands | identical, `0x0D` |
| D | send `DONE_REQ` | `DONE_RSP cmd=0x6`, as intended |

Without `DONE`, the device **remains in the Sahara state machine** and
interprets every subsequent byte as a Sahara packet. The sequence `END → DONE` is
mandatory. Hypothesis closed.

---

## 9. ZLP handling

When an OUT chunk is an exact multiple of 512 bytes, the host must send a
zero-length packet to terminate the transfer. Without it, the device waits for
more data and the session stalls.

The stall appeared at a suspiciously consistent point — after the 7th `READ_DATA`,
at 16 700 bytes:

```
[    1.065]   READ[7] off=197376 len=11376 total=16700
[    6.076] timeout loop=7 sent=16700/1569028
```

That offset is `0x30300`, and 11 376 bytes is a multiple of 512. Adding ZLP
handling removed this stall permanently.

> **Caution.** This stall *also* occurred when the battery was low, at the same
> offset. Two unrelated causes produced an identical symptom, which is why the
> power hypothesis survived as long as it did. See
> [`07-dead-ends.md`](07-dead-ends.md).

---

## 10. Timeout and retry behaviour

From measurement, not documentation:

- A `READ_DATA` request not answered within ~5–6 s leads to a dead session; the
  device does not re-request.
- Read retries with a widening timeout (`5000, 10000, 15000 ms`) recovered some
  sessions; write retries did not.
- Re-opening the handle after a failure mostly returns the zombie state described
  in [`05-firehose-and-the-silence.md`](05-firehose-and-the-silence.md): the
  endpoint is present in PnP but every transfer hangs.
- A power cycle (hold Power ~10–15 s) is the only reliable way out of a wedged
  state.

---

## 11. Minimal working uploader

The essence, stripped of logging and with explicit paths:

```python
dev = usb.core.find(idVendor=0x05C6, idProduct=0x9008)
dev.set_configuration(1)
usb.util.claim_interface(dev, 0)

pkt = read_packet()                       # HELLO_REQ
ver = struct.unpack_from("<I", pkt, 8)[0]
write(struct.pack("<IIIIIIIIIIII", 0x02, 0x30, ver, 1, 0, 0, 1, 2, 3, 4, 5, 6))

sent = 0
while True:
    pkt = read_packet()
    cmd = struct.unpack_from("<I", pkt, 0)[0]

    if cmd in (0x03, 0x12):
        if cmd == 0x03:
            img, off, dlen = struct.unpack_from("<III", pkt, 8)
        else:
            img, off, dlen = struct.unpack_from("<QQQ", pkt, 8)
        chunk = blob[off:off + dlen]
        if len(chunk) < dlen:
            chunk += b"\xff" * (dlen - len(chunk))
        write(chunk)                      # write() adds the ZLP when needed
        sent += len(chunk)

    elif cmd == 0x04:
        status = struct.unpack_from("<I", pkt, 8)[0]
        if status != 0:
            raise RuntimeError(f"END status {status:#x}")
        if sent < MIN_EXPECTED:           # never trust a short transfer
            raise RuntimeError("short transfer")
        write(struct.pack("<II", 0x05, 8))   # DONE
        break
```

Note the three things that took the longest to get right: buffered framing,
the ZLP, and the `MIN_EXPECTED` check.

The complete, commented version is [`scripts/sahara_upload.py`](../scripts/sahara_upload.py).
