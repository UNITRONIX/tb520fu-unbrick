#!/usr/bin/env python3
"""com_wait_read.py - open the port FIRST, then read one region.

The problem this solves
-----------------------
On a USB *bulk* endpoint a pending HELLO sits in a buffer and can be read whenever you
open the device. On a **serial port** it does not: bytes that arrive before the port is
open are discarded by the driver. So a script that waits for the COM port to appear and
then opens it has already lost the HELLO.

That is why every attempt so far reported "no HELLO" on a freshly power-cycled device.

The approach
------------
Poll aggressively for the port name, open the moment it exists, and hold the handle. The
device sends HELLO shortly after enumeration, and by then the port is already ours.

Also: never let the handle close mid-transfer. A Windows serial port in that state starts
failing every subsequent call with 'the device does not recognise the command'.

Read-only: one memory region, no image upload.

Usage
    python com_wait_read.py --region DDR_DATA.BIN
    python com_wait_read.py --region DDR_DATA.BIN --timeout 180
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial required: pip install pyserial")
    raise SystemExit(2)

OUT = Path(__file__).resolve().parent / "com_region_read"
T0 = time.time()

HELLO_REQ = 0x01
HELLO_RSP = 0x02
MEMORY_DEBUG = 0x09
MEMORY_READ = 0x0A
MEMORY_DEBUG_64 = 0x10
MEMORY_READ_64 = 0x11

MODE_MEMORY_DEBUG = 2


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


def find_qualcomm_port() -> str | None:
    """Return the COM name of a Qualcomm device, if one is enumerated."""
    for p in list_ports.comports():
        desc = (p.description or "") + " " + (p.hwid or "")
        if "05C6" in desc.upper() or "QCUSB" in desc.upper() or "QUALCOMM" in desc.upper():
            return p.device
    return None


def open_when_ready(timeout: float) -> serial.Serial | None:
    """Poll for the port and open it the instant it exists."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        name = find_qualcomm_port()
        if name and name != last:
            log(f"port {name} appeared - opening immediately")
            try:
                sp = serial.Serial(name, 115200, timeout=0.3, write_timeout=5.0)
                log("opened")
                return sp
            except Exception as err:  # noqa: BLE001
                log(f"open failed ({type(err).__name__}) - will retry")
        last = name or last
        time.sleep(0.05)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="DDR_DATA.BIN")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    print("=" * 74)
    print(f"#  wait-for-port, then read {args.region}")
    print("=" * 74)
    log("POWER CYCLE THE TABLET NOW if you have not already.")
    log("The port must be opened before HELLO arrives, so this waits for it.")

    sp = open_when_ready(args.timeout)
    if sp is None:
        log("no Qualcomm port appeared")
        return 1

    try:
        # HELLO should arrive within a second or two of enumeration.
        log("waiting for HELLO")
        buf = b""
        deadline = time.time() + 15
        pkt = None
        while time.time() < deadline:
            try:
                buf += sp.read(4096)
            except Exception as err:  # noqa: BLE001
                log(f"read error {type(err).__name__}")
                return 1
            if len(buf) >= 8:
                cmd, ln = struct.unpack_from("<II", buf, 0)
                if cmd == HELLO_REQ and 8 <= ln <= 4096:
                    if len(buf) >= ln:
                        pkt = buf[:ln]
                        buf = buf[ln:]
                        break
            time.sleep(0.05)

        if pkt is None:
            log("no HELLO (already consumed, or the device is mid-boot)")
            return 1

        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"HELLO ver={ver} mode={mode}")

        sp.write(struct.pack("<IIIIIIIIIIII", HELLO_RSP, 0x30,
                             ver, 1, 0, MODE_MEMORY_DEBUG, 1, 2, 3, 4, 5, 6))
        sp.flush()

        # read MEMORY_DEBUG reply
        deadline = time.time() + 8
        while time.time() < deadline and len(buf) < 8:
            buf += sp.read(4096)
            time.sleep(0.03)
        if len(buf) < 8:
            log("no MEMORY_DEBUG reply")
            return 1
        rcmd, rlen = struct.unpack_from("<II", buf, 0)
        while len(buf) < rlen:
            buf += sp.read(65536)
        rsp, buf = buf[:rlen], buf[rlen:]

        if rcmd == MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
            bit64 = False
        elif rcmd == MEMORY_DEBUG_64:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
            bit64 = True
        else:
            log(f"expected MEMORY_DEBUG, got {rcmd:#x}")
            return 1
        log(f"table @ {tbl_addr:#x} len {tbl_len} (64bit={bit64})")

        # request the table
        req = MEMORY_READ_64 if bit64 else MEMORY_READ
        if bit64:
            sp.write(struct.pack("<IIQQ", req, 24, tbl_addr, tbl_len))
        else:
            sp.write(struct.pack("<IIII", req, 16, tbl_addr, tbl_len))
        sp.flush()

        def recv(n: int, tmo: float = 15.0) -> bytes:
            nonlocal buf
            out = b""
            deadline2 = time.time() + tmo
            if buf:
                take = min(len(buf), n)
                out, buf = buf[:take], buf[take:]
            while len(out) < n and time.time() < deadline2:
                chunk = sp.read(min(65536, n - len(out)))
                if chunk:
                    out += chunk
            return out

        table = recv(tbl_len)
        log(f"table received: {len(table)} B")
        if len(table) < 64:
            log("table too short")
            return 1

        regions = []
        off = 0
        while off + 64 <= len(table):
            pref, addr, length = struct.unpack_from("<QQQ", table, off)
            fname = table[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
            desc = table[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
            if length == 0:
                break
            regions.append({"addr": addr, "len": length, "file": fname, "desc": desc})
            off += 64
        log(f"regions: {len(regions)}")

        if args.list:
            for r in regions:
                log(f"  {r['addr']:#014x} {r['len']:>12}  {r['file']:<20} {r['desc']}")
            return 0

        target = [r for r in regions if r["file"] == args.region]
        if not target:
            log(f"{args.region} not found; try --list")
            return 1
        r = target[0]
        log(f"reading {r['file']}  {r['len']} B @ {r['addr']:#x}")

        if bit64:
            sp.write(struct.pack("<IIQQ", req, 24, r["addr"], r["len"]))
        else:
            sp.write(struct.pack("<IIII", req, 16, r["addr"], r["len"]))
        sp.flush()

        data = recv(r["len"], tmo=40.0)
        log(f"received {len(data)}/{r['len']} B")

        if data:
            dest = OUT / r["file"]
            dest.write_bytes(data)
            log(f"saved {dest}")
            nz = sum(1 for b in data if b)
            log(f"nonzero: {nz}/{len(data)} ({nz/len(data)*100:.1f}%)")
            for i in range(0, min(96, len(data)), 16):
                h = " ".join(f"{b:02x}" for b in data[i:i + 16])
                t = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i + 16])
                log(f"  {i:04x}  {h}  |{t}|")
        return 0 if data else 1

    finally:
        try:
            sp.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
