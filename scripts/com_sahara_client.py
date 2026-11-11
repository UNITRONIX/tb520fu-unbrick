#!/usr/bin/env python3
"""com_sahara_client.py - Sahara over a Qualcomm COM port, with region order under our control.

Why this exists
---------------
Every custom Sahara client in this project so far spoke raw libusb, and therefore
needed the device bound to WinUSB. The vendor tool speaks the COM port, but it
walks the memory table strictly in ascending address order, which is why
DDR_DATA.BIN (the DDR training data, at the highest address in the whole table)
can never be reached: the walk stalls on DDRCS0_0 at 0x82800000 first.

No client existed that could talk to the device over COM *and* choose which
regions to read. This one does, so the two measurements that were blocked by
tooling become available:

    DDR_DATA.BIN     0x1000080000  256 KiB   "DDR Training Data"
    the table itself                        how much DDR the handler declares

and they can be read FIRST, before any multi-gigabyte window is touched.

Two facts from the notes make this straightforward rather than a race:

  * the tablet does not boot-loop; left alone it waits in 900E indefinitely
    (docs/23-no-boot-loop.md), so there is no absence window to catch;
  * the Qualcomm serial driver binds 900E and exposes it as a real port
    (docs/25-com-world-works.md measured COM10 on this unit).

Therefore: open the port, read the one pending HELLO, and use that single
session for everything. One HELLO per reset is a device property, so the script
does all its reads inside one handshake and never reopens mid-session.

Read-only. It performs a MEMORY_DEBUG handshake and MEMORY_READ_64 requests.
It does not switch mode, does not upload an image, and never writes storage.

Usage
    python com_sahara_client.py --list
    python com_sahara_client.py --port COM10 --table
    python com_sahara_client.py --port COM10 --grab DDR_DATA.BIN
    python com_sahara_client.py --port COM10 --priority
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import serial

# ---- Sahara protocol -----------------------------------------------------
CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_READ_DATA = 0x03
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_DONE_RSP = 0x06
CMD_RESET = 0x07
CMD_RESET_RSP = 0x08
CMD_MEMORY_DEBUG = 0x09
CMD_MEMORY_READ = 0x0A
CMD_CMD_READY = 0x0B
CMD_MEMORY_DEBUG_64 = 0x10
CMD_MEMORY_READ_64 = 0x11
CMD_MEMORY_READ_DATA_64 = 0x12

MODE_IMAGE_TX = 0
MODE_MEMORY_DEBUG = 2

OUT = Path(__file__).resolve().parent / "com_sahara"
T0 = time.time()

ENTRY = 64  # memory table stride


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


# ---- transport -----------------------------------------------------------
class SerialLink:
    """Sahara framing over a byte stream (no USB packet semantics).

    A COM port gives no packet boundaries, so the same rule as USB applies and
    for the same reason: read exactly `length` bytes and never assume one
    read() equals one packet. The USB ZLP rule does not apply here.
    """

    def __init__(self, port: str, baud: int, timeout: float = 3.0,
                 dtr: bool | None = None, rts: bool | None = None) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.2, write_timeout=3.0)
        # pyserial asserts DTR and RTS when it opens a port. On this device that is
        # a real signal change on the USB CDC side, and it is the one difference
        # between our open and the vendor tool's: QSaharaServer received a genuine
        # HELLO on the same port where our reader sees silence. Setting these
        # explicitly, after open, lets us test whether that is the cause.
        if dtr is not None:
            self.ser.dtr = dtr
        if rts is not None:
            self.ser.rts = rts
        self.buf = b""
        self.timeout = timeout
        # A dead port raises on every call forever. Without this counter the read
        # loops spin and produce tens of thousands of identical log lines, which
        # buries the actual result - the same class of harm as truncating output.
        self.errors = 0
        self.last_error = ""
        self.dead = False

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001
            pass

    def _fill(self, want: int = 4096) -> bytes:
        if self.dead:
            return b""
        try:
            data = self.ser.read(max(1, want))
            if data:
                self.errors = 0
            return data
        except Exception as err:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"{type(err).__name__}: {err}"
            if self.errors == 1:
                log(f"    port read error ({self.last_error})")
            if self.errors >= 8:
                self.dead = True
                log("    port stopped responding - ending this session "
                    "(a power cycle clears it; do not retry blindly)")
            return b""

    def read_packet(self, timeout: float | None = None):
        tmo = self.timeout if timeout is None else timeout
        deadline = time.time() + tmo
        while len(self.buf) < 8:
            if self.dead or time.time() > deadline:
                return None
            self.buf += self._fill(64)
        cmd, ln = struct.unpack_from("<II", self.buf, 0)
        if ln < 8 or ln > (1 << 20):
            raise RuntimeError(f"insane packet length {ln} (cmd={cmd:#x}) - bad framing")
        while len(self.buf) < ln:
            if self.dead or time.time() > deadline:
                return None
            self.buf += self._fill(4096)
        pkt, self.buf = self.buf[:ln], self.buf[ln:]
        return pkt

    def write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def mem_read(link: SerialLink, addr: int, length: int, tmo: float = 20.0) -> bytes:
    """MEMORY_READ_64 followed by `length` raw bytes.

    The payload comes back as raw bytes, not as a Sahara packet. Reading it as a
    packet desynchronises the session - the same trap recorded for EXECUTE in
    docs/15 s6.
    """
    link.write(struct.pack("<IIQQ", CMD_MEMORY_READ_64, 8 + 8 + 8, addr, length))
    got = bytearray()
    deadline = time.time() + tmo
    while len(got) < length and time.time() < deadline:
        if link.dead:
            break
        chunk = link._fill(min(65536, length - len(got)))
        if chunk:
            got += chunk
            deadline = time.time() + tmo  # progress resets the clock
    return bytes(got)


# ---- memory table --------------------------------------------------------
def parse_table(payload: bytes) -> list[dict]:
    """64-byte entries: qword save_pref | qword mem_base | qword length | desc[20] | file[20]"""
    out = []
    off = 0
    while off + ENTRY <= len(payload):
        pref, addr, length = struct.unpack_from("<QQQ", payload, off)
        desc = payload[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
        fname = payload[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
        if length == 0 or length > (1 << 36):
            break
        out.append({"pref": pref, "addr": addr, "len": length,
                    "desc": desc, "file": fname})
        off += ENTRY
    return out


def handshake(link: SerialLink, allow_reset: bool = False, retries: int = 2):
    """HELLO -> MEMORY_DEBUG -> table. Returns (version, table, raw_table).

    Measured on this unit (2026-11-11, twice, plus the vendor tool on the same
    port): SAHARA_RESET does NOT produce a new HELLO. The packet is emitted once
    per boot and consumed by whoever reads it first. So a reset is opt-in only
    (--allow-reset); by default this reports the situation and stops instead of
    hammering a device that cannot answer.
    """
    pkt = link.read_packet(3.0)
    if pkt is None and allow_reset:
        for attempt in range(retries):
            if link.dead:
                break
            log(f"  nothing pending - SAHARA_RESET (attempt {attempt + 1}/{retries})")
            try:
                link.write(struct.pack("<II", CMD_RESET, 8))
            except Exception as err:  # noqa: BLE001
                log(f"  reset not accepted: {type(err).__name__}")
                break
            for _ in range(4):
                pkt = link.read_packet(3.0)
                if pkt is None:
                    break
                c = struct.unpack_from("<I", pkt, 0)[0]
                if c == CMD_HELLO_REQ:
                    break
                if c == CMD_RESET_RSP:
                    continue
                pkt = None
            if pkt is not None:
                break
    if pkt is None:
        log("  no HELLO on the port.")
        log("  This is expected on a 900E node whose HELLO was already read: the")
        log("  device emits exactly one per boot, and a SAHARA_RESET does not")
        log("  regenerate it (measured twice, and with the vendor tool as control).")
        log("  To obtain one: power cycle the tablet, or use a port not yet opened.")
        return None, None, None
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd == CMD_END_TRANSFER:
        log("  stale END pending - closing it and re-reading")
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        pkt = link.read_packet(4.0)
        if pkt is None:
            return None, None, None
        cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO_REQ, got {cmd:#x} - the port is not in a fresh Sahara state")
        return None, None, None

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  HELLO ver={ver} mode={mode}")
    if mode != MODE_MEMORY_DEBUG:
        log(f"  mode={mode} is not MEMORY_DEBUG (2); this tool only reads crashdump")
        return None, None, None

    link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
    rsp = link.read_packet(6.0)
    if rsp is None:
        log("  no answer to HELLO_RSP")
        return None, None, None
    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
        log(f"  expected MEMORY_DEBUG, got {rcmd:#x}")
        return None, None, None

    if rcmd == CMD_MEMORY_DEBUG:
        tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
    else:
        tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
    log(f"  MEMORY_DEBUG{'_64' if rcmd == CMD_MEMORY_DEBUG_64 else ''}: "
        f"table @{tbl_addr:#x} len={tbl_len}")

    raw = mem_read(link, tbl_addr, tbl_len, tmo=8.0)
    log(f"  table bytes received: {len(raw)}/{tbl_len}")
    return ver, (parse_table(raw) if raw else None), raw


# ---- main ----------------------------------------------------------------
def cmd_list() -> int:
    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("no serial ports found")
        return 0
    for p in ports:
        print(f"{p.device:<10s} {p.description}   hwid={p.hwid}")
    return 0


def print_table(tables: list[dict]) -> None:
    log("")
    log(f"{'#':>3}  {'addr':>14}  {'len':>12}  {'pref':>4}  name")
    log("-" * 74)
    for i, e in enumerate(tables):
        log(f"{i:>3}  {e['addr']:#014x}  {e['len']:>12}  {e['pref']:>4}  "
            f"{e['file'] or e['desc']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list serial ports")
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--table", action="store_true", help="print the memory table only")
    ap.add_argument("--grab", default=None,
                    help="read one entry whose filename contains this string")
    ap.add_argument("--priority", action="store_true",
                    help="read DDR_DATA and the table first, in that order")
    ap.add_argument("--max", type=int, default=1 << 20,
                    help="per-entry size cap (bytes)")
    ap.add_argument("--allow-reset", action="store_true",
                    help="try SAHARA_RESET to provoke a HELLO (measured not to work "
                         "on this unit; off by default)")
    args = ap.parse_args()

    if args.list:
        return cmd_list()

    OUT.mkdir(exist_ok=True)
    log("=" * 74)
    log("#  com_sahara_client - Sahara over COM, region order under our control")
    log("=" * 74)

    try:
        link = SerialLink(args.port, args.baud)
    except Exception as err:  # noqa: BLE001
        log(f"  cannot open {args.port}: {type(err).__name__}: {err}")
        return 2

    try:
        ver, tables, raw = handshake(link, allow_reset=args.allow_reset)
        if tables is None:
            if raw:
                (OUT / "memory_table_raw.bin").write_bytes(raw)
                log("  saved the unparsed table for inspection")
            return 1

        (OUT / "memory_table_raw.bin").write_bytes(raw)
        print_table(tables)

        if args.table:
            return 0

        # ---- choose what to read, and in which order --------------------
        grabs: list[dict] = []
        if args.priority or args.grab:
            # DDR_DATA first: it is the region the vendor tool can never reach,
            # because it walks addresses ascending and stalls at 0x82800000.
            wanted = ["DDR_DATA"] if args.priority else [args.grab]
            for w in wanted:
                hits = [e for e in tables
                        if w.lower() in (e["file"] or "").lower()
                        or w.lower() in (e["desc"] or "").lower()]
                if not hits:
                    log(f"  no table entry matches {w!r}")
                grabs.extend(hits)

        # SHRM_MEM holds the DDR firmware's own structures and is small.
        if args.priority:
            grabs += [e for e in tables
                      if "SHRM" in (e["file"] or "").upper()]

        for e in grabs:
            name = e["file"] or e["desc"] or f"entry{e['addr']:#x}"
            if e["len"] > args.max:
                log("")
                log(f"  skipping {name}: {e['len']} B exceeds --max {args.max}")
                continue
            log("")
            log(f"  reading {name}  {e['len']} B @ {e['addr']:#x}  (requested FIRST)")
            blob = mem_read(link, e["addr"], e["len"], tmo=15.0)
            if blob:
                fn = OUT / f"{e['addr']:#014x}_{name.replace('/', '_')}"
                fn.write_bytes(blob)
                nz = sum(1 for b in blob if b)
                log(f"    got {len(blob)}/{e['len']} B  nonzero {nz / max(1, len(blob)):.1%} -> {fn.name}")
            else:
                log("    no data returned")

        log("")
        log(f"  artefacts in: {OUT}")
        return 0
    finally:
        # A clean close matters: an abandoned session leaves the node mute until
        # a power cycle (docs/15 s7). SAHARA_RESET (0x07), never 0x13.
        try:
            link.write(struct.pack("<II", CMD_RESET, 8))
            link.read_packet(2.0)
        except Exception:  # noqa: BLE001
            pass
        link.close()


if __name__ == "__main__":
    sys.exit(main())
