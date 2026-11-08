#!/usr/bin/env python3
"""
get_unlock_file.py - download the bootloader unlock file for a Lenovo tablet
directly over HTTP, without the web form or the confirmation email.

Background
----------
Lenovo's official unlock flow is https://www.zui.com/iunlock : you enter the
serial number, receive an email, then follow a link. That is slow and requires a
working mailbox.

The file the flow ultimately gives you is served from a plain, unauthenticated CDN
path with the serial number in the URL:

    http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img

No cookie, no token, no referer, no email. Verified on 2026-11-08:

    GET  -> HTTP 200, 5 386 B, Content-Type: application/octet-stream
    Last-Modified: Tue, 03 Nov 2026 18:33:53 GMT
    Range requests supported (206)

Use HTTPS only if you are willing to ignore the certificate: the CDN presents a
certificate that does not match cdn.zui.lenovomm.com, so plain HTTP is used by
default here. The payload is an X.509-signed image, so a tampered download will
be rejected by the bootloader anyway -- but do not treat the transport as private.

What you get
------------
An Android boot image (`ANDROID!` magic) whose "kernel" is an 8-byte stub and whose
real content is the per-serial authorisation:

    0x0000..0x0800   boot header page (page_size 2048)
    0x0800..0x0808   serial number, ASCII, NUL-padded to 8 bytes
    0x0808..0x1000   zero padding
    0x1000..end      X.509 certificate chain + signature (1290 B)

Because the certificate is issued per serial, a file downloaded for one device is
worthless for another. The serial is inside the signature, so it cannot be edited.

The server only answers for serials it knows: valid Lenovo serials return 200,
anything invented returns 404. It is not a public serial-number oracle beyond
that, and it is not a way to unlock a device you do not own.

Usage
-----
  python get_unlock_file.py --serial ABC12345
  python get_unlock_file.py --serial ABC12345 --out sn.img
  python get_unlock_file.py --serial ABC12345 --verify

  # see what the file contains without downloading twice
  python get_unlock_file.py --inspect sn.img --serial ABC12345
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://cdn.zui.lenovomm.com/developer/tabletboot"
HTTPS_BASE = "https://cdn.zui.lenovomm.com/developer/tabletboot"
USER_AGENT = "Mozilla/5.0 (compatible; tb520fu-unbrick unlock fetcher)"

#: Typical size of a minted unlock file. Not enforced, only reported.
EXPECTED_MIN = 1024
EXPECTED_MAX = 64 * 1024


def url_for(serial: str, https: bool = False) -> str:
    base = HTTPS_BASE if https else BASE
    return f"{base}/{serial}/sn.img"


def download(serial: str, timeout: float = 30.0, https: bool = False) -> bytes:
    """Fetch the unlock file. Raises on failure with a readable message."""
    url = url_for(serial, https=https)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rsp:
            data = rsp.read()
            status = rsp.status
            length = rsp.headers.get("Content-Length")
            last_mod = rsp.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(
                f"404 for serial {serial!r}.\n"
                f"  URL: {url}\n"
                f"The server only serves serials it knows. Check the number -\n"
                f"  - it is on the box, on the SIM tray, or via 'adb shell getprop ro.serialno'\n"
                f"  - it is usually 8 characters, uppercase letters and digits\n"
                f"  - no spaces, no prefix such as 'S/N'"
            ) from exc
        raise SystemExit(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        hint = ""
        if https:
            hint = ("\nIf this is a certificate error, the CDN certificate does not match\n"
                    "the hostname. Use plain HTTP (the default) instead of --https.")
        raise SystemExit(f"network error for {url}: {exc.reason}{hint}") from exc

    if status != 200:
        raise SystemExit(f"unexpected HTTP status {status} for {url}")
    if not data:
        raise SystemExit("server returned an empty body")

    print(f"downloaded {len(data)} B  (HTTP {status})")
    if length:
        print(f"  Content-Length : {length}")
    if last_mod:
        print(f"  Last-Modified  : {last_mod}")
    print(f"  sha256         : {hashlib.sha256(data).hexdigest()}")
    return data


def inspect(data: bytes, serial: str | None) -> int:
    """Describe the file, and confirm it is bound to `serial`."""
    print()
    print("=== FILE CONTENTS ===")
    if data[:8] != b"ANDROID!":
        print(f"  magic: {data[:8]!r} - NOT an Android boot image")
        print("  This is not the file type this tool expects. Do not flash it.")
        return 2
    print("  magic: ANDROID! (Android boot image)")

    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, _second_addr, _tags_addr, page_size) = struct.unpack_from("<8I", data, 8)
    print(f"  kernel_size  : {kernel_size}  (a stub - the real payload is the signature)")
    print(f"  ramdisk_size : {ramdisk_size}")
    print(f"  page_size    : {page_size}")

    if page_size <= 0 or page_size > len(data):
        print("  page_size looks wrong; cannot map the layout")
        return 2

    # serial lives at the start of the payload area
    offset = page_size
    field = data[offset:offset + 8]
    embedded = field.split(b"\x00")[0].decode("ascii", "replace")
    print(f"  serial field : {embedded!r} at 0x{offset:X}")

    if serial:
        if embedded.upper() == serial.upper():
            print("  -> MATCHES the serial you asked for")
        else:
            print(f"  -> MISMATCH: file is bound to {embedded!r}, not {serial!r}")
            print("     This file will be refused by your device. Do not flash it.")

    cert = data.find(b"\x30\x82", page_size)
    if cert >= 0:
        print(f"  X.509 chain  : starts at 0x{cert:X}, {len(data) - cert} B "
              f"(certificate + signature)")
        print("                 issued per serial, cannot be edited without the key")
    else:
        print("  no X.509 SEQUENCE found - unexpected for this file type")
    print()
    print(f"  total size   : {len(data)} B")
    print(f"  sha256       : {hashlib.sha256(data).hexdigest()}")
    return 0 if (serial is None or embedded.upper() == serial.upper()) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download a Lenovo tablet bootloader unlock file over HTTP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--serial", help="device serial number, e.g. ABC12345")
    ap.add_argument("--out", type=Path, default=Path("sn.img"),
                    help="output path (default: sn.img)")
    ap.add_argument("--https", action="store_true",
                    help="use HTTPS; the CDN certificate does not match the host, "
                         "so this usually needs verification disabled")
    ap.add_argument("--inspect", type=Path, default=None,
                    help="do not download; describe an existing file")
    ap.add_argument("--verify", action="store_true",
                    help="after downloading, confirm the embedded serial matches")
    args = ap.parse_args(argv)

    if args.inspect is not None:
        if not args.inspect.is_file():
            print(f"ERROR: no such file: {args.inspect}")
            return 2
        return inspect(args.inspect.read_bytes(), args.serial)

    if not args.serial:
        print("ERROR: --serial is required (or use --inspect FILE)")
        return 2

    serial = args.serial.strip().upper()
    if serial != args.serial.strip():
        print(f"note: normalising serial to {serial!r}")

    print(f"serial: {serial}")
    print(f"url   : {url_for(serial, https=args.https)}")
    print()

    data = download(serial, https=args.https)

    if not (EXPECTED_MIN <= len(data) <= EXPECTED_MAX):
        print(f"warning: {len(data)} B is outside the expected range "
              f"({EXPECTED_MIN}-{EXPECTED_MAX}); inspect before using it")

    if args.verify:
        rc = inspect(data, serial)
        if rc != 0:
            print("NOT saving a file that does not match the requested serial.")
            return rc
    elif data[:8] == b"ANDROID!":
        embedded = data[struct.unpack_from("<I", data, 36)[0]:][:8].split(b"\x00")[0]
        try:
            text = embedded.decode("ascii")
        except UnicodeDecodeError:
            text = ""
        if text and text.upper() != serial.upper():
            print(f"warning: embedded serial is {text!r}, not {serial!r}; "
                  f"run with --verify to see the details")

    args.out.write_bytes(data)
    print()
    print(f"saved: {args.out}  ({len(data)} B)")
    print()
    print("Next step - unlocking the bootloader:")
    print("  fastboot flash unlock sn.img")
    print("  fastboot oem unlock-go        # some builds; otherwise confirm on screen")
    print()
    print("Unlocking wipes userdata. Back up first.")
    print("See docs/12-bootloader-unlock.md for the full procedure and caveats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
