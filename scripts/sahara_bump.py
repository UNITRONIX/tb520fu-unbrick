#!/usr/bin/env python3
"""
sahara_bump.py - move the device from crashdump (05c6:900e) to real EDL
(05c6:9008).

Why this exists
---------------
On TB520FU the device does not come up in EDL by itself. It boots into crashdump,
which speaks Sahara in mode=2 (MEMORY_DEBUG) - a RAM-dump mode where a zero-byte
transfer is acknowledged as success. Loading a programmer requires mode=0
(IMAGE_TX_PENDING), which in practice means moving the USB endpoint to 9008.

The sequence, as measured on this device:

    HELLO ver=2 mode=2                       crashdump, as expected
    HELLO_RSP(mode=3)                        ask for COMMAND mode
    <- 0x0B SAHARA_CMD_READY
    SWITCH_MODE(0)                           0x0C, 12 bytes
    <- 0x01 HELLO_REQ                        this re-HELLO is the success signal
    HELLO_RSP(mode=0)                        confirm IMAGE_TX_PENDING
    <- 0x04 END_TRANSFER status=0             empty image closed
    DONE_REQ
    ... device re-enumerates as 9008 ~20 s later ...

The switch itself is instantaneous. The re-enumeration is not: 20.8 s in the
recorded session. Scripts that time out after 2-3 s conclude the bump failed while
it is still in progress, and then leave the device in an intermediate state.

See docs/14-edl-mode-switch.md for every variant tried and every pitfall.

This script is read-only with respect to storage. It changes the device's USB mode
and nothing else.

Usage
-----
  python sahara_bump.py                  # wait for 900e, bump, confirm 9008
  python sahara_bump.py --timeout 40     # allow longer for re-enumeration
  python sahara_bump.py --wait 0         # do not wait; 900e must be present now
  python sahara_bump.py --once           # single attempt, no reset retry

  # if already on 9008 and only the empty END is needed:
  python sahara_bump.py --from-9008

Requirements
------------
  pip install pyusb
  WinUSB bound to 05c6:900e / 05c6:9008 (not the Qualcomm COM driver).
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("pyusb is required:  pip install pyusb", file=sys.stderr)
    raise SystemExit(2)

VID = 0x05C6
PID_EDL = 0x9008
PID_CRASH = 0x900E

EP_IN, EP_OUT = 0x81, 0x01

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_SAHARA_RESET = 0x07
CMD_RESET_RSP = 0x08
CMD_CMD_READY = 0x0B
CMD_SWITCH_MODE = 0x0C

MODE_IMAGE_TX_PENDING = 0x00
MODE_IMAGE_TX_COMPLETE = 0x01
MODE_MEMORY_DEBUG = 0x02
MODE_COMMAND = 0x03

IMAGE_ID_PROGRAMMER = 0x0D

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def u32(buf: bytes, off: int = 0) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def hello_rsp(version: int, mode: int) -> bytes:
    """HELLO_RSP: 12 fields, 0x30 bytes. Must echo the device's version."""
    return struct.pack(
        "<IIIIIIIIIIII",
        CMD_HELLO_RSP, 0x30, version, 1, 0, mode, 1, 2, 3, 4, 5, 6,
    )


class Link:
    """Buffered packet I/O. read() can return several packets, or part of one."""

    def __init__(self, dev):
        self.dev = dev
        self.buf = b""

    def _chunk(self, ms: int):
        try:
            return bytes(self.dev.read(EP_IN, 65536, timeout=ms))
        except usb.core.USBTimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001
            log(f"    read exception {type(exc).__name__}: {exc}")
            return b""

    def read_packet(self, timeout_ms: int = 3000, retries: int = 2):
        for attempt in range(retries):
            deadline = time.time() + (timeout_ms * (attempt + 1)) / 1000.0
            ok = True
            while len(self.buf) < 8:
                left = int((deadline - time.time()) * 1000)
                if left <= 0:
                    ok = False
                    break
                c = self._chunk(min(left, 300))
                if c is None:
                    continue
                if c == b"":
                    ok = False
                    break
                self.buf += c
            if not ok:
                continue

            cmd, length = struct.unpack_from("<II", self.buf, 0)
            if length < 8 or length > (1 << 20):
                log(f"    bad header cmd=0x{cmd:X} len={length}; dropping buffer")
                self.buf = b""
                return None

            while len(self.buf) < length:
                left = int((deadline - time.time()) * 1000)
                if left <= 0:
                    ok = False
                    break
                c = self._chunk(min(left, 300))
                if c is None:
                    continue
                if c == b"":
                    ok = False
                    break
                self.buf += c
            if not ok:
                continue

            pkt, self.buf = self.buf[:length], self.buf[length:]
            return pkt
        return None

    def write(self, data: bytes, timeout_ms: int = 4000) -> bool:
        try:
            self.dev.write(EP_OUT, data, timeout=timeout_ms)
            return True
        except Exception as exc:  # noqa: BLE001
            log(f"    write exception {type(exc).__name__}: {exc}")
            return False

    def drain(self, rounds: int = 8) -> int:
        total = 0
        for _ in range(rounds):
            try:
                c = bytes(self.dev.read(EP_IN, 65536, timeout=100))
            except Exception:  # noqa: BLE001
                break
            if not c:
                break
            total += len(c)
        self.buf = b""
        return total


def present(pid: int) -> bool:
    return usb.core.find(idVendor=VID, idProduct=pid) is not None


def open_dev(pid: int, retries: int = 4, delay: float = 0.5):
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
                log(f"  claim_interface: {exc}")
            return dev
        if attempt + 1 < retries:
            time.sleep(delay)
    return None


def close_dev(dev) -> None:
    for fn in (lambda: usb.util.release_interface(dev, 0),
               lambda: usb.util.dispose_resources(dev)):
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


def wait_for_hello(link: Link, do_reset: bool = True):
    """Read until HELLO_REQ. Handle a pending END_TRANSFER by resetting.

    Returns the HELLO packet, or None.
    """
    pkt = link.read_packet(4000, retries=1)

    if pkt is None:
        if not do_reset:
            return None
        log("  nothing pending -> SAHARA_RESET")
        link.write(struct.pack("<II", CMD_SAHARA_RESET, 8))
        r = link.read_packet(1500, retries=1)
        if r:
            log(f"  reset response cmd=0x{u32(r):X}")
        link.drain(6)
        pkt = link.read_packet(5000, retries=2)
        if pkt is None:
            return None

    cmd = u32(pkt)
    log(f"  pending cmd=0x{cmd:X}")

    if cmd == CMD_END_TRANSFER:
        # A previous session ended badly. The device waits for a reset.
        status = u32(pkt, 8) if len(pkt) >= 12 else -1
        log(f"  pending END status=0x{status:X} -> SAHARA_RESET")
        if not do_reset:
            return None
        link.write(struct.pack("<II", CMD_SAHARA_RESET, 8))
        link.read_packet(1500, retries=1)
        link.drain(6)
        pkt = link.read_packet(5000, retries=2)
        if pkt is None:
            return None
        cmd = u32(pkt)
        log(f"  after reset cmd=0x{cmd:X}")

    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO_REQ, got 0x{cmd:X}")
        return None
    return pkt


def bump_once(timeout_s: float, do_reset: bool = True) -> bool:
    """One full 900e -> 9008 attempt."""
    if present(PID_EDL):
        log("already on 9008")
        return True

    dev = open_dev(PID_CRASH)
    if dev is None:
        log("no device on 900e")
        return False

    link = Link(dev)
    try:
        pkt = wait_for_hello(link, do_reset=do_reset)
        if pkt is None:
            log("could not reach HELLO on 900e")
            return False

        version = u32(pkt, 8)
        mode = u32(pkt, 20) if len(pkt) >= 24 else 0
        label = {0: "IMAGE_TX (already EDL?)",
                 2: "crashdump",
                 3: "COMMAND"}.get(mode, "unknown")
        log(f"  HELLO ver={version} mode={mode}  <- {label}")

        if mode == MODE_IMAGE_TX_PENDING:
            # Already in IMAGE_TX, e.g. after an interrupted session.
            # Do not switch; just close the empty transfer.
            log("  already IMAGE_TX -> empty END")
            link.write(struct.pack(
                "<IIII", CMD_END_TRANSFER, 16, 0, IMAGE_ID_PROGRAMMER))
            r = link.read_packet(2000, retries=1)
            if r and u32(r) == CMD_END_TRANSFER:
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                link.read_packet(1500, retries=1)
        else:
            # 1. Ask for COMMAND mode.
            if not link.write(hello_rsp(version, MODE_COMMAND)):
                return False
            r = link.read_packet(3000, retries=1)
            if r is None:
                log("  no response to HELLO_RSP(mode=3)")
                return False
            rc = u32(r)
            log(f"  COMMAND -> 0x{rc:X}"
                f"{' (CMD_READY)' if rc == CMD_CMD_READY else ''}")

            # 2. Switch to IMAGE_TX_PENDING. Exactly 12 bytes: cmd, len, mode.
            if not link.write(struct.pack(
                    "<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX_PENDING)):
                return False
            r = link.read_packet(3000, retries=1)
            if r is None:
                log("  no response to SWITCH_MODE")
                return False
            rc = u32(r)
            log(f"  switch -> 0x{rc:X}"
                f"{' (HELLO re-issued: success)' if rc == CMD_HELLO_REQ else ''}")
            if rc != CMD_HELLO_REQ:
                return False

            # 3. Confirm the version the device just asked with.
            new_version = u32(r, 8)
            if not link.write(hello_rsp(new_version, MODE_IMAGE_TX_PENDING)):
                return False
            r = link.read_packet(2500, retries=1)
            if r is None:
                log("  no response after HELLO_RSP(mode=0)")
                return False
            rc = u32(r)
            log(f"  after ITX -> 0x{rc:X}"
                f"{' (END_TRANSFER: expected)' if rc == CMD_END_TRANSFER else ''}")

            # 4. Close the exchange.
            if rc == CMD_END_TRANSFER:
                status = u32(r, 8) if len(r) >= 12 else -1
                log(f"  empty END status=0x{status:X}"
                    f"{' (ok)' if status == 0 else ''}")
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                link.read_packet(1500, retries=1)
            elif rc != CMD_HELLO_REQ:
                log("  unexpected response; continuing to wait anyway")
    except Exception as exc:  # noqa: BLE001
        log(f"  exception {type(exc).__name__}: {exc}")
        return False
    finally:
        close_dev(dev)

    log(f"  waiting up to {timeout_s:.0f}s for 9008 (measured: ~20s)")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if present(PID_EDL):
            time.sleep(0.3)
            log("  now on 9008")
            return True
        time.sleep(0.1)
    log("  9008 did not appear")
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Move the device from crashdump (900e) to EDL (9008).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--timeout", type=float, default=40.0,
                    help="seconds to wait for 9008 after the switch (default 40)")
    ap.add_argument("--wait", type=float, default=120.0,
                    help="seconds to wait for a 900e device to appear "
                         "(default 120; 0 means do not wait)")
    ap.add_argument("--once", action="store_true",
                    help="single attempt, no reset-and-retry")
    ap.add_argument("--from-9008", action="store_true",
                    help="only close an empty IMAGE_TX transfer on 9008; "
                         "no mode switch")
    args = ap.parse_args(argv)

    if args.from_9008:
        if not present(PID_EDL):
            log("nothing on 9008")
            return 1
        dev = open_dev(PID_EDL)
        if dev is None:
            return 1
        link = Link(dev)
        try:
            link.write(struct.pack(
                "<IIII", CMD_END_TRANSFER, 16, 0, IMAGE_ID_PROGRAMMER))
            r = link.read_packet(2000, retries=1)
            log(f"  response: {'none' if r is None else hex(u32(r))}")
            if r and u32(r) == CMD_END_TRANSFER:
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
                link.read_packet(1500, retries=1)
        finally:
            close_dev(dev)
        return 0

    if args.wait > 0:
        log(f"waiting up to {args.wait:.0f}s for 900e (or 9008)...")
        deadline = time.time() + args.wait
        while time.time() < deadline:
            if present(PID_EDL):
                log("already on 9008")
                return 0
            if present(PID_CRASH):
                log("900e present")
                break
            time.sleep(0.05)
        else:
            log("no device appeared")
            return 1

    attempts = 1 if args.once else 2
    for i in range(1, attempts + 1):
        log(f"=== attempt {i}/{attempts} ===")
        if bump_once(args.timeout, do_reset=True):
            log("bump OK")
            return 0
        if i < attempts:
            log("retrying after a short pause")
            time.sleep(1.0)

    log("bump FAILED")
    log("If 9008 never appears: power-cycle the device (hold Power ~15 s) and")
    log("retry. Do not unplug the cable while the device is mid-negotiation.")
    log("See docs/14-edl-mode-switch.md section 4.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
