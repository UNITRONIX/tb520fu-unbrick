#!/usr/bin/env python3
"""
sahara_upload.py - strict-framing Sahara uploader over raw libusb.

This is the cleaned-up descendant of the scripts that finally made the transport
work on TB520FU. It contains the three fixes that mattered, each marked FIX below:

  1. buffered framing  - read() can return several packets at once
  2. ZLP               - needed after any OUT chunk that is a multiple of 512
  3. MIN_SENT check    - END status 0x0 with zero bytes is a false success

It is READ-ONLY with respect to the device's storage: it uploads a programmer into
RAM and then optionally probes. Writing partitions requires a working Firehose
session, which on this device never happens.

Requirements
------------
  pip install pyusb
  On Windows you also need a WinUSB driver bound to 05c6:9008/900e
  (Zadig, or libwdi). Do NOT use the Qualcomm COM drivers with this script -
  they are mutually exclusive. See docs/07-dead-ends.md section A6.

Usage
-----
  # list what is on the USB bus
  python sahara_upload.py probe

  # upload a programmer and listen afterwards (the useful case)
  python sahara_upload.py upload --programmer path/to/xbl_s_devprg_ns.melf

  # upload and then actively probe with XML commands
  python sahara_upload.py upload --programmer ... --probe

  # just read what the device says, without uploading anything
  python sahara_upload.py listen --seconds 10
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import usb.core
    import usb.util
except ImportError:
    print("pyusb is required:  pip install pyusb", file=sys.stderr)
    raise SystemExit(2)

from sahara_codes import describe_nak

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VID = 0x05C6
PID_EDL = 0x9008        # genuine EDL
PID_CRASHDUMP = 0x900E  # crashdump / diagnostics

EP_IN = 0x81
EP_OUT = 0x01
MAXPKT = 512

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_READ_DATA = 0x03
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_RESET = 0x07
CMD_READ_DATA_64 = 0x12

#: Sahara never requests the trailing padding of the programmer, so the byte count
#: is always less than the file size. This is the minimum we accept as "the whole
#: programmer was actually transferred" for the SM8650 devprg used on TB520FU.
MIN_SENT_DEFAULT = 1_554_996

XML_NOP = b'<?xml version="1.0" ?><data><nop /></data>'
XML_CONFIGURE = (
    b'<?xml version="1.0" ?><data>'
    b'<configure MemoryName="ufs" Verbose="1" AlwaysValidate="0" '
    b'MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" '
    b'ZlpAwareHost="1" SkipStorageInit="0"/></data>'
)


class Link:
    """Buffered packet I/O over the Sahara bulk endpoints."""

    def __init__(self, dev, verbose: bool = True):
        self.dev = dev
        self.buf = b""
        self.verbose = verbose

    # -- low level ---------------------------------------------------------
    def _read_chunk(self, timeout_ms: int):
        try:
            return bytes(self.dev.read(EP_IN, 65536, timeout=timeout_ms))
        except usb.core.USBTimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001
            if self.verbose:
                print(f"    read exception {type(exc).__name__}: {exc}")
            return b""

    def read_packet(self, timeout_ms: int = 5000, retries: int = 3):
        """Return one complete Sahara packet, or None.

        FIX 1: the device may deliver several packets in a single read(), and a
        packet may span reads. Always consume exactly `length` bytes.
        """
        for attempt in range(retries):
            deadline = time.time() + (timeout_ms * (attempt + 1)) / 1000.0
            ok = True

            while len(self.buf) < 8:
                left = int((deadline - time.time()) * 1000)
                if left <= 0:
                    ok = False
                    break
                chunk = self._read_chunk(min(left, 400))
                if chunk is None:
                    continue
                if chunk == b"":
                    ok = False
                    break
                self.buf += chunk
            if not ok:
                continue

            cmd, length = struct.unpack_from("<II", self.buf, 0)
            if length < 8 or length > (1 << 20):
                if self.verbose:
                    print(f"    bad header cmd=0x{cmd:X} len={length}")
                self.buf = b""
                return None

            while len(self.buf) < length:
                left = int((deadline - time.time()) * 1000)
                if left <= 0:
                    ok = False
                    break
                chunk = self._read_chunk(min(left, 400))
                if chunk is None:
                    continue
                if chunk == b"":
                    ok = False
                    break
                self.buf += chunk
            if not ok:
                continue

            pkt, self.buf = self.buf[:length], self.buf[length:]
            return pkt
        return None

    def write(self, data: bytes, timeout_ms: int = 8000, zlp: bool = True) -> bool:
        try:
            self.dev.write(EP_OUT, data, timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            if self.verbose:
                print(f"    write exception {type(exc).__name__}: {exc}")
            return False
        # FIX 2: terminate transfers that are an exact multiple of the packet size
        if zlp and data and len(data) % MAXPKT == 0:
            try:
                self.dev.write(EP_OUT, b"", timeout=2000)
            except Exception:  # noqa: BLE001
                pass
        return True


def hello_rsp(version: int, mode: int = 0) -> bytes:
    """HELLO_RSP must echo the version the device asked for."""
    return struct.pack(
        "<IIIIIIIIIIII",
        CMD_HELLO_RSP, 0x30, version, 1, 0, mode, 1, 2, 3, 4, 5, 6,
    )


def open_device(pid: int = PID_EDL, retries: int = 4, delay: float = 0.6):
    for attempt in range(retries):
        dev = usb.core.find(idVendor=VID, idProduct=pid)
        if dev is not None:
            try:
                dev.set_configuration(1)
            except Exception:  # noqa: BLE001
                pass
            try:
                usb.util.claim_interface(dev, 0)
            except Exception as exc:  # noqa: BLE001
                print(f"  claim_interface: {exc}")
            return dev
        if attempt + 1 < retries:
            time.sleep(delay)
    return None


def close_device(dev) -> None:
    for fn in (lambda: usb.util.release_interface(dev, 0),
               lambda: usb.util.dispose_resources(dev)):
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


def device_present(pid: int) -> bool:
    return usb.core.find(idVendor=VID, idProduct=pid) is not None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_probe() -> int:
    print("Scanning for Qualcomm devices (VID 05c6)...")
    found = False
    for pid, label in ((PID_EDL, "EDL (9008)"),
                       (PID_CRASHDUMP, "crashdump / diagnostics (900e)")):
        present = device_present(pid)
        print(f"  05c6:{pid:04x}  {label:34s} {'PRESENT' if present else 'absent'}")
        found = found or present
    if not found:
        print()
        print("No 05c6 device. Check the cable, and check that the device is")
        print("actually in EDL or crashdump (not merely powered on).")
        return 1
    print()
    print("Reminder: WinUSB and the Qualcomm COM drivers are mutually exclusive.")
    print("Raw libusb / pyusb needs WinUSB.")
    return 0


def cmd_listen(seconds: float) -> int:
    dev = open_device(PID_EDL)
    if dev is None:
        print("No device on 05c6:9008.")
        return 1
    link = Link(dev)
    print(f"Reading for {seconds:.0f}s without sending anything...")
    deadline = time.time() + seconds
    total = 0
    while time.time() < deadline:
        chunk = link._read_chunk(200)
        if chunk:
            total += len(chunk)
            print(f"  +{len(chunk)} B: {chunk[:64]!r}")
    close_device(dev)
    print(f"total: {total} B")
    if total == 0:
        print()
        print("Silence. If this was after an upload, the programmer is not running.")
        print("See docs/05-firehose-and-the-silence.md")
    return 0


def cmd_upload(programmer: Path, probe_after: bool, passive_seconds: float,
               min_sent: int) -> int:
    if not programmer.is_file():
        print(f"ERROR: no such file: {programmer}")
        return 2

    blob = programmer.read_bytes()
    print(f"programmer: {programmer.name}  {len(blob)} B")
    if min_sent > len(blob):
        print(f"WARNING: --min-sent ({min_sent}) exceeds file size ({len(blob)}); "
              f"clamping to file size")
        min_sent = len(blob)

    dev = open_device(PID_EDL)
    if dev is None:
        print("No device on 05c6:9008. If it is on 900e, that is crashdump -")
        print("you need a mode switch first (see docs/03-sahara-protocol.md).")
        return 1

    link = Link(dev)
    result = upload(link, blob, min_sent)

    if result["status"] != "done":
        print()
        print(f"UPLOAD DID NOT COMPLETE: {result['status']} (sent {result['sent']} B)")
        close_device(dev)
        return 1

    print()
    print("=" * 68)
    print("Programmer accepted. Now listening (this is the part that matters).")
    print("=" * 68)
    banner = passive_capture(link, passive_seconds)
    if banner:
        print()
        print(f"*** DEVICE SPOKE: {len(banner)} B ***")
        print(hexdump(banner))
        close_device(dev)
        return 0

    print()
    print("Silence after DONE.")

    if probe_after:
        for name, payload in (("nop", XML_NOP), ("configure", XML_CONFIGURE)):
            print(f"  active probe: {name}")
            ok = link.write(payload, zlp=False)
            if not ok:
                print("    write refused")
                continue
            rsp = link.read_packet(2000, retries=1)
            if rsp:
                print(f"    *** ANSWER: {len(rsp)} B ***")
                print(hexdump(rsp))
                close_device(dev)
                return 0
            print("    silence")

    print()
    print("The programmer is accepted but never appears as a Firehose endpoint.")
    print("On TB520FU this is where the investigation ends. See")
    print("  docs/05-firehose-and-the-silence.md")
    print("  docs/11-faq.md")
    close_device(dev)
    return 1


def upload(link: Link, blob: bytes, min_sent: int) -> dict:
    """Run the HELLO/READ_DATA/END/DONE sequence. Returns a result dict."""
    res = {"status": "init", "sent": 0, "end": None, "version": None, "mode": None}

    pkt = link.read_packet(8000, retries=2)
    if pkt is None:
        res["status"] = "no_hello"
        return res

    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        res["status"] = f"expected_hello_got_0x{cmd:X}"
        return res

    version = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0] if len(pkt) >= 24 else 0
    res["version"], res["mode"] = version, mode

    label = {0: "genuine EDL from PBL", 2: "crashdump (memory debug)"}.get(mode, "unknown")
    print(f"  HELLO ver={version} mode={mode}   <- {label}")

    if not link.write(hello_rsp(version), zlp=False):
        res["status"] = "hello_write_failed"
        return res

    sent = 0
    loops = 0
    while loops < 50000:
        pkt = link.read_packet(6000, retries=3)
        if pkt is None:
            res["status"] = "stall"
            res["sent"] = sent
            return res

        cmd = struct.unpack_from("<I", pkt, 0)[0]

        if cmd == CMD_HELLO_REQ:
            link.write(hello_rsp(version), zlp=False)
            continue

        if cmd in (CMD_READ_DATA, CMD_READ_DATA_64):
            if cmd == CMD_READ_DATA_64:
                _img, off, dlen = struct.unpack_from("<QQQ", pkt, 8)
            else:
                _img, off, dlen = struct.unpack_from("<III", pkt, 8)
            chunk = blob[off:off + dlen]
            if len(chunk) < dlen:
                chunk += b"\xff" * (dlen - len(chunk))
            if not link.write(chunk):
                res["status"] = "write_failed"
                res["sent"] = sent
                return res
            sent += len(chunk)
            loops += 1
            if loops <= 10 or loops % 30 == 0:
                print(f"  READ[{loops}] off={off} len={dlen} total={sent}")
            continue

        if cmd == CMD_END_TRANSFER:
            status = struct.unpack_from("<I", pkt, 8)[0] if len(pkt) >= 12 else -1
            res["end"] = status
            res["sent"] = sent
            print(f"  END status=0x{status:X}  bytes={sent}/{len(blob)}")
            if status != 0:
                print("  " + describe_nak(status))
                res["status"] = f"end_0x{status:X}"
                return res

            # FIX 3: a zero-byte transfer can be acknowledged as success in mode=2
            if sent < min_sent:
                print(f"  SHORT TRANSFER: {sent} < {min_sent} - refusing to call "
                      f"this a success")
                res["status"] = "short_transfer"
                return res

            link.write(struct.pack("<II", CMD_DONE_REQ, 8), zlp=False)
            ack = link.read_packet(4000, retries=2)
            if ack:
                print(f"  DONE response cmd=0x{struct.unpack_from('<I', ack, 0)[0]:X}")
            else:
                print("  DONE: no response")
            res["status"] = "done"
            return res

        res["status"] = f"unexpected_cmd_0x{cmd:X}"
        res["sent"] = sent
        return res

    res["status"] = "loop_limit"
    return res


def passive_capture(link: Link, seconds: float) -> bytes:
    """Read only. Send nothing. Stop 1 s after the last byte."""
    buf = bytearray()
    deadline = time.time() + seconds
    last_data = None
    while time.time() < deadline:
        chunk = link._read_chunk(120)
        if chunk:
            buf += chunk
            last_data = time.time()
            print(f"  passive +{len(chunk)} B")
        if last_data and (time.time() - last_data) > 1.0:
            break
    return bytes(buf)


def hexdump(data: bytes, limit: int = 512) -> str:
    data = data[:limit]
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"    {i:04x}  {hexpart:<47}  {text}")
    if len(data) == limit:
        lines.append("    ...")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Strict-framing Sahara uploader over raw libusb.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="scan the USB bus for Qualcomm devices")

    p_listen = sub.add_parser("listen", help="read without sending anything")
    p_listen.add_argument("--seconds", type=float, default=10.0)

    p_up = sub.add_parser("upload", help="upload a programmer and listen afterwards")
    p_up.add_argument("--programmer", required=True, type=Path,
                      help="path to the .melf programmer")
    p_up.add_argument("--probe", action="store_true",
                      help="send nop/configure after the passive capture")
    p_up.add_argument("--passive-seconds", type=float, default=6.0,
                      help="how long to listen silently after DONE (default 6)")
    p_up.add_argument("--min-sent", type=int, default=MIN_SENT_DEFAULT,
                      help=f"minimum bytes for a valid transfer "
                           f"(default {MIN_SENT_DEFAULT})")

    args = ap.parse_args(argv)

    if args.command == "probe":
        return cmd_probe()
    if args.command == "listen":
        return cmd_listen(args.seconds)
    return cmd_upload(args.programmer, args.probe, args.passive_seconds, args.min_sent)


if __name__ == "__main__":
    sys.exit(main())
