# Scripts

Standalone tools extracted from the recovery effort. All are in English, take
explicit paths, print readable logs, and **none of them write to the device's
storage**.

---

## What these scripts are and are not

They are the tooling that made the protocol legible: packet framing, container
inspection, hash hunting, and the passive capture that finally proved the
programmer never starts.

They are **not** an unbrick tool. No script here can restore the tablet, because
the blocker is that Firehose never comes up. Scripts that would write partitions
are deliberately absent — there was never a working session to write from.

---

## Requirements

```
pip install pyusb
```

On Windows you also need **WinUSB** bound to `05c6:9008` and `05c6:900e` (Zadig, or
`libwdi`). This is mutually exclusive with the Qualcomm COM drivers: WinUSB means
`pyusb`, COM means `fh_loader`/QFIL, and neither can see the device while the other
driver is bound.

Check which world you are in:

```powershell
powershell -ExecutionPolicy Bypass -File usb_watch/Kill-Orphans.ps1
```

That prints the service bound to each Qualcomm node, which tells you immediately
which tools can work.

---

## The tools

### `get_unlock_file.py` — bootloader unlock file over HTTP

Fetches the per-device unlock token from Lenovo's CDN without the web form or the
confirmation email.

```bash
python get_unlock_file.py --serial <SERIAL> --verify
python get_unlock_file.py --inspect sn.img --serial <SERIAL>
```

`--verify` parses the image and refuses to save a file whose embedded serial does
not match the one requested. `--inspect` describes an existing file: header fields,
serial at `0x800`, and the offset of the X.509 chain.

The endpoint, why HTTPS is broken there, and the per-serial signing are documented
in [`../docs/12-bootloader-unlock.md`](../docs/12-bootloader-unlock.md).

Note this script writes a file to **your disk** — that is its whole purpose. It
does not touch the device.

---

### `sahara_bump.py` — crashdump to EDL

Moves the device from `05c6:900e` (crashdump) to `05c6:9008` (real EDL), which is
where a programmer can actually be loaded.

```bash
python sahara_bump.py                 # wait for 900e, bump, confirm 9008
python sahara_bump.py --timeout 60    # allow longer for re-enumeration
python sahara_bump.py --from-9008     # only close a stale IMAGE_TX transfer
```

Handles the three starting states automatically: `HELLO` pending (normal), `END`
pending (reset first), and nothing pending (reset, then read). `--from-9008` covers
the case where the device is already in `IMAGE_TX` and only needs the empty
`END`/`DONE` exchange.

The measured timing is baked into the defaults: the switch completes in under a
millisecond, but re-enumeration took **20.8 s**, so the default wait is 40 s.
Documented in [`../docs/14-edl-mode-switch.md`](../docs/14-edl-mode-switch.md).

---

### `sahara_codes.py` — the code tables

Every Sahara command and NAK code, with the vendor range above `0x28` clearly
marked. The notes record what each interesting code actually meant on this device,
which is not always what the name suggests.

```bash
python sahara_codes.py          # full table
python sahara_codes.py 0x29     # explain one code
```

Worth reading before interpreting any error. `0x0D` in particular is usually the
host's fault, not the device's.

---

### `melf_tool.py` — container inspection

The tool that made the melf understandable: `info`, `split`, `patch`, `verify`.

```bash
python melf_tool.py info   --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf
python melf_tool.py split  --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf --out melf_parts
python melf_tool.py verify --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf
```

`verify` is the interesting one: it confirms the tool's model of the format by
reassembling the pieces and comparing to the original byte for byte. If that passes,
the container's structure is genuinely understood — which is what lets you say with
confidence which parts of it are code and which are metadata.

---

### `analyze_melf_map.py` — regions and the Firehose identity

Maps the data regions, computes the trailing padding, and optionally compares the
embedded Firehose image against a standalone programmer ELF.

```bash
python analyze_melf_map.py --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf \
                           --standalone <ROM_DIR>/image/prog_firehose_ddr.elf
```

The output that matters from that comparison: the standalone file is contained
**bit for bit** inside the container. Same code, wrong envelope. Which is why
re-signing the standalone file was never going to work.

---

### `find_hashes.py` — proving the hash is not in the file

Computes several digest variants of every inner image and searches the whole
container for them. On TB520FU: none present under any standard algorithm.

```bash
python find_hashes.py --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf
```

It also disassembles the wrapper interior region by region, which is how the
"`0x1000..0x1300` is empty" claim from an earlier note was found to be wrong: a
652-byte tag/length metadata blob lives at `0x1074..0x1300`.

Run this before attempting any per-image modification. If it finds no digest of the
inner images, the substitution route has nothing to recompute — but the wrapper
metadata *does* contain one digest (of itself), so see `tlv_parse.py` and
`hash_sweep.py` before concluding the file has no hashes at all.

---

### `tlv_parse.py` — decode the wrapper metadata blob

Walks the 652-byte region at `0x1074..0x1300` with the correct schema: little-endian
`u16 tag | u16 len`, values padded to 4 bytes. Consumes 652/652 bytes and prints the
full tree, including the `0x8441` digest and the two `0x81FF` blocks.

```bash
python tlv_parse.py [--melf <path>]
```

### `hash_sweep.py` — exhaustive digest sweep

Builds a candidate set from every program-header segment of every ELF image (raw,
`0xFF`-stripped, `0x00`-stripped) plus whole-file and TLV-range variants — 84
candidates — and tests each against every hash-sized TLV value with 9 algorithms.

Result on TB520FU: exactly one match, `sha512(wrapper ph[0], 4096 B)` == tag `0x8441`.
Nothing else.

### `verify_tlv.py` — cross-build comparison

Compares the blob (and the whole file) across ZUI 17.5.10.096, ZUI 18.5.10.037 and
the device backup `stock_18.5_ref`. Reports differing byte counts, the first and last
difference, and how many differences fall inside the TLV region.

Result: 33 779 differing bytes between builds, **0 inside the TLV**, TLV SHA-256
identical in all three.

---

### `build_signed_melf.py` — reproducing the 0x21 result

Rebuilds the container with one image replaced, verifying that everything else is
untouched and all program headers stay in bounds.

```bash
python build_signed_melf.py --melf <ROM_DIR>/image/xbl_s_devprg_ns.melf \
    --replace prog_firehose_ddr-signed-v7.mbn \
    --out xbl_s_devprg_ns_SIGNED_FH.melf \
    --pad-to-original
```

`--pad-to-original` trims trailing zeros so the total size is unchanged, which
removes "the image shifted" as a variable.

Expect the device to reject this with `0x21` at an offset **before** the replaced
image. That is the point: it demonstrates the container is verified as a whole.
Reproducing it takes minutes and settles the question for your firmware revision.

---

### `sahara_upload.py` — the uploader that works

Strict framing, ZLP handling, and a minimum-byte check, over raw libusb.

```bash
python sahara_upload.py probe
python sahara_upload.py upload --programmer <ROM_DIR>/image/xbl_s_devprg_ns.melf
python sahara_upload.py listen --seconds 10
```

The `upload` command prints the passive capture result after `DONE`, which is the
interesting part. `listen` reads without uploading anything, useful for checking
whether a device that claims to be in EDL is actually talking.

Contains the three fixes worth knowing about:

| Fix | Symptom it removes |
|---|---|
| buffered framing | `0xD` errors that look like device faults |
| ZLP after 512-byte-aligned chunks | stall at exactly 16 700 bytes |
| `MIN_SENT` check | `END 0x0` on a zero-byte transfer reported as success |

---

### `banner_capture.py` — listen instead of talk

Uploads the programmer, then sends **nothing** for several seconds and only reads.
Adds the crashdump→EDL mode switch, so it can start from either state.

```bash
python banner_capture.py --programmer <ROM_DIR>/image/xbl_s_devprg_ns.melf --attempts 5
```

This separates two things every earlier session conflated: "the programmer started
and printed a banner" from "the programmer never started". On TB520FU the answer is
the second, repeatably.

If a banner does appear, it will say what the programmer wants (VIP digest table,
storage init, and so on) — which is exactly the information that was never obtained.

---

### `usb_watch/FastUsbWatch.cs` — presence at 0.15 ms

Enumerates every USB device interface via SetupAPI in a tight loop with no sleep.
No WMI, no libusb, no VID filter, so nothing is filtered out by assumption.

```bash
csc FastUsbWatch.cs
FastUsbWatch.exe 120 fastusb.log
```

The measurement this enabled: 584 042 polls in 90 s, and during a 15.0 s window the
tablet was absent from the bus **in every form**. That is what ruled out the "hidden
fastboot during the logo" theory, which had been the most persistent wrong idea in
the whole effort.

---

### `usb_watch/Kill-Orphans.ps1` — clear the USB handle

Lists python processes that look like EDL clients, and optionally stops them.

```powershell
powershell -ExecutionPolicy Bypass -File usb_watch/Kill-Orphans.ps1        # dry run
powershell -ExecutionPolicy Bypass -File usb_watch/Kill-Orphans.ps1 -Kill  # stop them
```

Run this first when `usb_class` reports `Permission denied`. Leftover processes hold
the handle and produce exactly that error, which looks like a driver problem and is
not.

The script is deliberately conservative about what it kills: it matches EDL-specific
strings in the command line and skips anything containing `mcp`, `ms-python`,
`pylance`, `jupyter` or `ipykernel`.

---

## Placeholders

The scripts take paths on the command line. Where the notes show `<ROM_DIR>`, that
is the extracted Lenovo RSA package, typically:

```
<ROM_DIR>/image/xbl_s_devprg_ns.melf     the programmer (melf container)
<ROM_DIR>/image/xbl_s.melf               1 117 008 B prefix, no DDR image
<ROM_DIR>/image/prog_firehose_ddr.elf    standalone Firehose (same code as inner image 3)
```

Nothing in this repository includes those files. See `docs/11-faq.md` §16–17.

---

## Safety notes

- These scripts **upload a programmer into RAM**. That does not modify storage.
  The programmer is what would write; it never ran.
- `Kill-Orphans.ps1 -Kill` stops processes. Dry run first.
- `FastUsbWatch.exe` runs a busyloop and will use one CPU core for the whole run.
- Do not alternate between the WinUSB and COM worlds in one session. Pick one and
  stay in it.
