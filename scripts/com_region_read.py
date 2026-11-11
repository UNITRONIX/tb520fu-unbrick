#!/usr/bin/env python3
"""com_region_read.py - read ONE memory region over the COM port.

Why this is needed
------------------
QSaharaServer in memory-debug mode dumps **every** declared region, in reverse table
order. DDR_DATA.BIN ("DDR Training Data", 0x1000080000, 256 KiB) is entry 40 of 53, so
the tool reaches it only after ~13 GB of DDR windows — which takes minutes and consumes
the whole session. Two attempts have been stopped before getting there.

What this does instead:

  1. open the COM port directly
  2. perform the Sahara handshake (HELLO -> HELLO_RSP MEMORY_DEBUG)
  3. read the memory table the target hands over
  4. request ONLY the named region
  5. write it to disk and close

Same protocol as the vendor tool, but selective. Read-only: no image is uploaded and
nothing is written to the device.

The COM port is a serial port, not a USB bulk endpoint, so the transfer framing differs
from the pyusb path: Sahara packets still have the 8-byte header and explicit length, and
the read payload arrives as raw bytes of exactly the requested length.

Usage
    python com_region_read.py --region DDR_DATA.BIN
    python com_region_read.py --region DDR_DATA.BIN --port COM10
    python com_region_read.py --list
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import serial
except ImportError:
    print("pyserial is required: python -m pip install pyserial")
    raise SystemExit(2)

OUT = Path(__file__).resolve().parent / "com_region_read"
T0 = time.time()

#: Sahara commands.
HELLO_REQ = 0x01
HELLO_RSP = 0x02
READ_DATA = 0x03
END_TRANSFER = 0x04
DONE_REQ = 0x05
DONE_RSP = 0x06
RESET = 0x07
RESET_RSP = 0x08
MEMORY_DEBUG = 0x09
MEMORY_READ = 0x0A
CMD_READY = 0x0B
MEMORY_DEBUG_64 = 0x10
MEMORY_READ_64 = 0x11
MEMORY_READ_DATA_64 = 0x12

MODE_MEMORY_DEBUG = 2


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}] {m}", flush=True)


class ComLink:
    """Sahara framing over a serial port."""

    def __init__(self, port: str, baud: int = 115200) -> None:
        self.sp = serial.Serial(port, baud, timeout=1.0, write_timeout=5.0)
        self.buf = b""

    def close(self) -> None:
        try:
            self.sp.close()
        except Exception:  # noqa: BLE001
            pass

    def _fill(self, n: int = 65536, tmo: float = 1.0) -> bytes:
        self.sp.timeout = tmo
        try:
            return self.sp.read(n)
        except Exception:  # noqa: BLE001
            return b""

    def read_packet(self, tmo: float = 5.0):
        deadline = time.time() + tmo
        while len(self.buf) < 8:
            if time.time() > deadline:
                return None
            self.buf += self._fill(4096, 0.2)
        cmd, ln = struct.unpack_from("<II", self.buf, 0)
        if ln < 8 or ln > (1 << 20):
            raise RuntimeError(f"insane length {ln} (cmd={cmd:#x})")
        while len(self.buf) < ln:
            if time.time() > deadline:
                return None
            self.buf += self._fill(65536, 0.2)
        pkt, self.buf = self.buf[:ln], self.buf[ln:]
        return pkt

    def read_raw(self, n: int, tmo: float = 10.0) -> bytes:
        out = b""
        if self.buf:
            out, self.buf = self.buf[:n], self.buf[n:]
        deadline = time.time() + tmo
        while len(out) < n and time.time() < deadline:
            chunk = self._fill(min(65536, n - len(out)), 0.5)
            if chunk:
                out += chunk
        return out

    def write(self, data: bytes) -> None:
        self.sp.write(data)
        self.sp.flush()


def parse_table(payload: bytes) -> list[dict]:
    out = []
    off = 0
    while off + 64 <= len(payload):
        pref, addr, length = struct.unpack_from("<QQQ", payload, off)
        desc = payload[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
        fname = payload[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
        if length == 0 or length > (1 << 40):
            break
        out.append({"pref": pref, "addr": addr, "len": length,
                    "desc": desc, "file": fname})
        off += 64
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--region", default="DDR_DATA.BIN")
    ap.add_argument("--list", action="store_true", help="list regions and exit")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    print("=" * 74)
    print("#  selective region read over COM")
    print("=" * 74)

    try:
        link = ComLink(args.port)
    except Exception as err:  # noqa: BLE001
        log(f"cannot open {args.port}: {err}")
        log("the port disappears when the device is not enumerated; power cycle first")
        return 1

    try:
        log(f"opened {args.port}")

        pkt = link.read_packet(3.0)
        if pkt is None:
            log("no HELLO. The single HELLO per power cycle is already consumed.")
            log("Power cycle the tablet, then run this FIRST.")
            return 1

        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != HELLO_REQ:
            log(f"expected HELLO, got {cmd:#x}")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"HELLO ver={ver} mode={mode}")

        link.write(struct.pack("<IIIIIIIIIIII", HELLO_RSP, 0x30,
                               ver, 1, 0, MODE_MEMORY_DEBUG, 1, 2, 3, 4, 5, 6))

        rsp = link.read_packet(5.0)
        if rsp is None:
            log("no answer to HELLO_RSP")
            return 1
        rcmd = struct.unpack_from("<I", rsp, 0)[0]
        if rcmd == MEMORY_DEBUG:
            tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
            bit64 = False
        elif rcmd == MEMORY_DEBUG_64:
            tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
            bit64 = True
        else:
            log(f"expected MEMORY_DEBUG, got {rcmd:#x}")
            return 1
        log(f"memory table @ {tbl_addr:#x}  len {tbl_len}  (64-bit={bit64})")

        # read the table itself
        req = MEMORY_READ_64 if bit64 else MEMORY_READ
        if bit64:
            link.write(struct.pack("<IIQQ", req, 8 + 8 + 8, tbl_addr, tbl_len))
        else:
            link.write(struct.pack("<IIII", req, 8 + 4 + 4, tbl_addr, tbl_len))
        table = link.read_raw(tbl_len, tmo=10.0)
        log(f"table bytes: {len(table)}")

        regions = parse_table(table)
        log(f"regions: {len(regions)}")

        if args.list:
            for r in regions:
                log(f"  {r['addr']:#014x} {r['len']:>12}  {r['file']:<20} {r['desc']}")
            return 0

        target = [r for r in regions if r["file"] == args.region]
        if not target:
            log(f"region {args.region!r} not in the table. Try --list.")
            return 1
        r = target[0]
        log(f"reading {r['file']}: {r['len']} B @ {r['addr']:#x}")

        if bit64:
            link.write(struct.pack("<IIQQ", req, 8 + 8 + 8, r["addr"], r["len"]))
        else:
            link.write(struct.pack("<IIII", req, 8 + 4 + 4, r["addr"], r["len"]))

        data = link.read_raw(r["len"], tmo=30.0)
        log(f"received {len(data)} of {r['len']} bytes")

        if data:
            dest = OUT / r["file"]
            dest.write_bytes(data)
            log(f"written to {dest}")

            nz = sum(1 for b in data if b)
            log(f"nonzero bytes: {nz}/{len(data)} ({nz/len(data)*100:.1f}%)")
            log("first 64 bytes:")
            for i in range(0, min(64, len(data)), 16):
                hexs = " ".join(f"{b:02x}" for b in data[i:i + 16])
                txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i + 16])
                log(f"  {i:04x}  {hexs}  |{txt}|")
        else:
            log("no data returned")

        return 0 if data else 1
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
