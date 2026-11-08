# Bootloader unlock file over HTTP

Lenovo's official unlock flow goes through a web form and a confirmation email. The
file it eventually hands you is served from a plain, unauthenticated CDN path with
the serial number in the URL. This document records the endpoint, what the file
contains, and the caveats.

**Measured on 2026-11-08.** Endpoint behaviour can change; verify before relying
on it.

---

## 1. The endpoint

```
http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img
```

Nothing else is needed — no cookie, no token, no referer, no session, no email.

### What the server returned

```
HTTP/1.1 200 OK
Content-Type: application/octet-stream
Content-Length: 5386
Last-Modified: Tue, 03 Nov 2026 18:33:53 GMT
ETag: "6aea2911-150a"
Cache-Control: max-age=3600
Accept-Ranges: bytes
Server: ZWS/1.12.1
```

Timing on a normal connection: **~0.09 s**, roughly 60 KB/s for this file size.
Range requests are supported (`Range: bytes=0-99` → `206`), which is irrelevant for
5 KB but means resumable fetches work if needed.

### Use the script

```bash
python scripts/get_unlock_file.py --serial <SERIAL> --verify
```

It downloads, checks the embedded serial actually matches, and only then saves. See
[`../scripts/README.md`](../scripts/README.md).

### Or the raw command

```bash
curl -O http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img
```

`curl -O` keeps the filename (`sn.img`). On PowerShell, `curl` is an alias for
`Invoke-WebRequest`, so use `curl.exe` or:

```powershell
Invoke-WebRequest -Uri "http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img" -OutFile sn.img
```

---

## 2. Where the serial number comes from

The serial is **8 characters, uppercase letters and digits** on the units seen
here. Find it from:

| Method | Command / location |
|---|---|
| On the device (Android running, USB debugging) | `adb shell getprop ro.serialno` |
| In fastboot | `fastboot getvar serialno` |
| On the packaging | the label on the box |
| Settings | Settings → About tablet → Status |

The value is **not** the model (`TB520FU`), not the IMEI, and not the build
fingerprint. Do not include a prefix such as `S/N:` and do not include spaces.

---

## 3. What is inside the file

It is an Android boot image, but not a bootable one: the kernel is an 8-byte stub.
The real content is the per-device authorisation.

```
0x0000..0x0800   Android boot header page (page_size = 2048)
0x0800..0x0808   serial number, ASCII, NUL-padded to 8 bytes
0x0808..0x1000   zero padding
0x1000..0x150A   X.509 certificate chain + signature (1290 B)
                 CN=Android, O=Lenovo, L=BEIJING, C=CN
```

### The certificate is per serial

Downloading for two different serials produces files that differ in exactly three
regions:

| Region | Size | What changes |
|---|---|---|
| `0x0240..0x0253` | 20 B | header field, varies per file |
| `0x0800..0x0807` | 8 B | the serial itself |
| `0x140A..0x1509` | 256 B | the signature over the certificate |

So **a file downloaded for one device will not unlock another**. The signature
covers the serial, and editing the 8 serial bytes invalidates it. There is no
"generic unlock file".

### The server only serves known serials

This was tested, because it determines whether the endpoint can be used as a
serial-number oracle:

| Serial | Response |
|---|---|
| a real serial | `200` |
| `00000000`, `12345678` | `200` (format-valid, present in the database) |
| `AAAAAAAA`, `13579246`, `TB520FU1`, `ABCD1234` | `404` |

The response is an HTML 404 page from `ZWS/1.12.1`. So the path resolves only
against serials the server already knows about — it does not mint a file for an
arbitrary string. That also means a typo produces a clean 404 rather than a
plausible-looking wrong file, which is a useful failure mode.

It is still not a way to unlock hardware you do not own: the file is bound to a
serial, and the device checks that serial against its own.

---

## 4. HTTPS does not work properly

```
https://cdn.zui.lenovomm.com/...   ->  certificate hostname mismatch
                                      (SEC_E_WRONG_PRINCIPAL / wrong principal)
```

The certificate presented does not match `cdn.zui.lenovomm.com`. It works only if
you disable verification (`curl -k`), which defeats the point. **The script
therefore uses plain HTTP by default** and offers `--https` only for completeness.

Is that a problem? Partially:

- The payload is X.509-signed, so a corrupted or substituted download will be
  rejected by the bootloader rather than flashed. Integrity is protected at the
  payload level.
- The transport is **not** private. Someone on the path can see which serial you
  requested, and can deny service.
- Practically: fetch it once, verify the embedded serial with `--verify`, and keep
  the file. There is no reason to download repeatedly.

---

## 5. Unlocking

```bash
# device in fastboot (Power + Vol- , or: adb reboot bootloader)

# confirm you are talking to the right device
fastboot getvar product          # expect: lapis
fastboot getvar serialno         # must match the serial you downloaded for

# flash the unlock token
fastboot flash unlock sn.img

# some builds need this, others prompt on screen
fastboot oem unlock-go

# or, if `flashing unlock` is supported directly:
fastboot flashing unlock
```

Then `fastboot reboot`.

### What happens next

**Unlocking wipes userdata.** This is not optional and not recoverable.

On first boot after unlocking, Android may report:

> Can't load Android system

That is the expected factory-reset state — choose **factory data reset** and let it
complete.

Verify the result:

```bash
adb shell getprop ro.boot.flash.locked      # expect: 0
adb shell getprop ro.boot.verifiedbootstate # expect: orange
```

---

## 6. Caveats, stated plainly

**Warranty.** Unlocking voids it. On this device that was accepted deliberately; if
warranty matters to you, do not do this.

**This is the step that starts everything.** In this project, unlocking was
followed by a Magisk root, a broken pivot initramfs, and finally a bootloader
replaced with one built for different hardware. The unlock itself is safe and
reversible in the sense that it can be re-locked; what followed it was not. Read
[`01-timeline.md`](01-timeline.md) before proceeding to anything after unlocking.

**Re-locking is risky.** `fastboot flashing lock` on a device with a modified or
missing boot chain can hard-brick it, because a locked bootloader refuses to boot
anything it does not verify and you may have nothing left that verifies. Do not
re-lock a device that is not fully stock.

**Endpoint longevity is unknown.** This CDN path is undocumented and unofficial
from Lenovo's perspective — it is simply the final hop of their own flow. It could
disappear. The script reports 404 clearly if it does.

**Do not share the file.** It is bound to your serial and is not a useful gift to
anyone else. Sharing the serial is also unwise: it identifies your specific unit.

---

## 7. Summary

| Question | Answer |
|---|---|
| Is there an HTTP endpoint? | Yes: `http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img` |
| Does it need the email flow? | No. No auth of any kind. |
| Does it need HTTPS? | No, and HTTPS is currently broken (hostname mismatch). |
| Is the file generic? | No. Signed per serial; will not work on another device. |
| Can the serial inside be edited? | No, the signature covers it. |
| Does it work for invented serials? | No, 404. |
| What does unlocking cost? | Warranty, and all userdata. |
| Where to get it | `python scripts/get_unlock_file.py --serial <SERIAL> --verify` |
