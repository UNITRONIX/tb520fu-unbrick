#!/usr/bin/env python3
"""crash_region_probe.py - enumerate what the 900E crashdump will actually give us.

Why this exists
---------------
Every previous session treated 05C6:900E as a doorway: bump to 9008, upload a
programmer, fail. The 900E state itself was only ever poked at two hard-coded
addresses (ddr_peek.py tried 0x9fa00000 once and got 0xFF -> "unmapped").

That is the wrong instrument. In SAHARA_MODE_MEMORY_DEBUG the device hands the
host a *table* describing exactly which memory ranges the crash handler is
willing to expose, with a human-readable name for each ("OCIMEM", "CODERAM",
"DATARAM", "RST_STAT", DDR windows, ...). Reading arbitrary addresses is what
we did; reading the table tells us where the data actually is.

This script does exactly that and nothing else:

  1. Saharara MEMORY_DEBUG handshake on 900E
  2. fetch the device's own memory table
  3. print every entry (address, length, description, filename)
  4. sample the first bytes of each entry and classify the content
  5. optionally read one full entry to a file (--grab NAME)

Strictly read-only. No writes, no mode switch, no image upload. If the device
is not in crashdump the script says so and exits without touching anything.

Usage
    python crash_region_probe.py                 # table + content map
    python crash_region_probe.py --grab PMIC_PON.BIN
    python crash_region_probe.py --full          # dump every entry <= --max
    python crash_region_probe.py --time 180      # wait for a fresh cycle
"""
from __future__ import annotations

import argparse
import atexit
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

# ---- Sahara --------------------------------------------------------------
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

OUT = Path(__file__).resolve().parent / "crash_region_probe"
T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


# ---- transport -----------------------------------------------------------
class Link:
    """Sahara framing: read() returns arbitrary chunks, never trust one == one packet."""

    def __init__(self, dev) -> None:
        self.dev = dev
        cfg = dev.get_active_configuration()
        self.ep_in = usb.util.find_descriptor(
            cfg[(0, 0)], custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN)
        self.ep_out = usb.util.find_descriptor(
            cfg[(0, 0)], custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT)
        self.buf = b""

    def _fill(self, timeout_ms: int = 1000) -> bytes:
        try:
            return bytes(self.ep_in.read(0x10000, timeout_ms))
        except usb.core.USBError as err:
            if "Timeout" in str(err) or "timed out" in str(err):
                return b""
            raise

    def read_packet(self, timeout_ms: int = 5000):
        deadline = time.time() + timeout_ms / 1000.0
        while len(self.buf) < 8:
            if time.time() > deadline:
                return None
            self.buf += self._fill(200)
        cmd, ln = struct.unpack_from("<II", self.buf, 0)
        if ln < 8 or ln > (1 << 20):
            raise RuntimeError(f"insane packet length {ln} (cmd={cmd:#x}) - bad framing")
        while len(self.buf) < ln:
            if time.time() > deadline:
                return None
            self.buf += self._fill(200)
        pkt, self.buf = self.buf[:ln], self.buf[ln:]
        return pkt

    def write(self, data: bytes) -> None:
        self.ep_out.write(data, 5000)
        # ZLP when the chunk is an exact multiple of the 512-byte max packet
        if len(data) % 512 == 0:
            try:
                self.ep_out.write(b"", 1000)
            except usb.core.USBError:
                pass


def open_device():
    dev = usb.core.find(idVendor=0x05C6, idProduct=0x900E)
    if dev is None:
        return None
    try:
        dev.set_configuration(1)
    except usb.core.USBError:
        pass
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError:
        pass
    return dev


# ---- memory table --------------------------------------------------------
ENTRY = 64


def parse_table(payload: bytes) -> list[dict]:
    """64-bit entry: qword save_pref | qword mem_base | qword length | desc[20] | filename[20]

    Layout confirmed against edlclient's parttbl_64bit and pon_probe.py, which
    both work on this device. 64-byte stride.
    """
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


def mem_read(link: Link, addr: int, length: int, tmo: float = 3.0) -> bytes:
    pkt = struct.pack("<IIQQ", CMD_MEMORY_READ_64, 8 + 8 + 8, addr, length)
    try:
        link.write(pkt)
    except Exception:  # noqa: BLE001
        return b""
    got = bytearray()
    deadline = time.time() + tmo
    while len(got) < length and time.time() < deadline:
        try:
            chunk = link._fill(150)
        except Exception:  # noqa: BLE001
            break
        if not chunk:
            continue
        got += chunk
    return bytes(got)


# ---- classification ------------------------------------------------------
def classify(blob: bytes) -> str:
    if not blob:
        return "no answer"
    head = blob[:16]
    if head[:4] == b"\x7fELF":
        return "*** ELF ***"
    if all(b == 0xFF for b in blob[:256]):
        return "0xFF fill (not mapped / not dumpable)"
    nz = sum(1 for b in blob if b)
    if nz == 0:
        return "all zeros"
    printable = sum(1 for b in blob[:512] if 32 <= b < 127 or b in (9, 10, 13))
    if printable > len(blob[:512]) * 0.85:
        txt = blob[:120].split(b"\x00")[0].decode("ascii", "replace")
        return f"ASCII text: {txt!r}"
    words = struct.unpack_from(f"<{min(len(blob), 4096)//4}I", blob, 0)
    plausible = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
    ratio = plausible / max(1, len(words))
    tag = "ARM64-code-like" if ratio > 0.85 else "data"
    return f"{tag} (nonzero {nz / len(blob):.0%}, code-like {ratio:.0%}) head={head.hex(' ')}"


def _read_hello(link: Link, attempts: int = 3, tmo: int = 3000):
    """Read packets until HELLO arrives, tolerating RESET_RSP and END_TRANSFER.

    After SAHARA_RESET the device replies RESET_RSP (0x08) and only then sends a
    fresh HELLO. Reading a single packet therefore stops on the RESET_RSP and
    reports 'expected HELLO, got cmd=0x8' - a state that looks broken but is
    simply mid-handshake. This drains up to `attempts` packets looking for HELLO.
    """
    for _ in range(attempts):
        try:
            pkt = link.read_packet(tmo)
        except Exception as err:  # noqa: BLE001
            # A pipe error here means the device reset out from under us, which
            # happens constantly on a boot-looping unit. Treat it as "no packet"
            # rather than letting it kill the caller.
            log(f"  read interrupted ({type(err).__name__}) - device probably reset")
            return None
        if pkt is None:
            return None
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd == CMD_HELLO_REQ:
            return pkt
        if cmd == CMD_RESET_RSP:
            continue          # expected after SAHARA_RESET; keep reading
        if cmd == CMD_END_TRANSFER:
            # a stale transfer: close it, then keep reading for HELLO
            try:
                link.write(struct.pack("<II", CMD_DONE_REQ, 8))
            except Exception:  # noqa: BLE001
                pass
            continue
        # anything else is not part of a clean open
        return pkt
    return None


def handshake_memory_debug(dev):
    """Return (link, tables) or None. Never switches mode, never uploads."""
    link = Link(dev)
    pkt = _read_hello(link, attempts=2, tmo=2500)
    if pkt is None:
        log("  nothing pending - trying SAHARA_RESET (0x07), NOT 0x13")
        try:
            link.write(struct.pack("<II", CMD_RESET, 8))
        except Exception as err:  # noqa: BLE001
            log(f"  reset not accepted ({type(err).__name__}) - device mid-cycle")
            return None, None
        pkt = _read_hello(link, attempts=4, tmo=3000)
    if pkt is None:
        log("  device does not answer Sahara at all")
        return None, None

    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO, got cmd={cmd:#x}")
        return None, None

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  HELLO ver={ver} mode={mode}")

    if mode != MODE_MEMORY_DEBUG:
        log(f"  mode={mode} is not crashdump (2). This script only reads crashdump.")
        return None, None

    # echo the version the device asked for, request MEMORY_DEBUG
    link.write(struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                           ver, 1, 0, MODE_MEMORY_DEBUG, 1, 2, 3, 4, 5, 6))

    rsp = link.read_packet(5000)
    if rsp is None:
        log("  no answer to HELLO_RSP")
        return None, None
    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    if rcmd not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
        log(f"  expected MEMORY_DEBUG, got cmd={rcmd:#x} (device in error state?)")
        return None, None

    if rcmd == CMD_MEMORY_DEBUG:
        tbl_addr, tbl_len = struct.unpack_from("<II", rsp, 8)
    else:  # 64-bit form has no entry count: just addr and length, both qword
        tbl_addr, tbl_len = struct.unpack_from("<QQ", rsp, 8)
    log(f"  MEMORY_DEBUG{'_64' if rcmd == CMD_MEMORY_DEBUG_64 else ''}: "
        f"table@{tbl_addr:#x} len={tbl_len}")

    table = mem_read(link, tbl_addr, tbl_len, tmo=4.0)
    if not table:
        log("  table read failed")
        close_session(link)
        return link, None
    # Register BEFORE returning so the atexit hook closes this session even if the
    # caller raises or exits without closing. Registering only on a later success
    # path is what left nodes wedged: an abandoned session stays mute until a power
    # cycle, and the hook never saw it.
    _OPEN_LINKS.append(link)
    return link, parse_table(table)


def close_session(link: Link) -> None:
    """End a MEMORY_DEBUG session cleanly.

    Leaving a session hanging is what produces the 'zombie' node: present in PnP,
    mute to every subsequent open, cleared only by a power cycle. A SAHARA_RESET
    (0x07 - never 0x13) returns the target to a fresh state.
    """
    try:
        link.write(struct.pack("<II", CMD_RESET, 8))
        link.read_packet(1500)
    except Exception:  # noqa: BLE001
        pass


#: Sessions opened via handshake_memory_debug, closed automatically at exit.
_OPEN_LINKS: list[Link] = []


def _close_all() -> None:
    for lk in _OPEN_LINKS:
        close_session(lk)


atexit.register(_close_all)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=120.0,
                    help="how long to wait for a usable 900E node (s)")
    ap.add_argument("--grab", default=None,
                    help="read one full entry whose filename contains this")
    ap.add_argument("--full", action="store_true", help="dump every entry")
    ap.add_argument("--max", type=int, default=1 << 20,
                    help="per-entry size cap when dumping (bytes)")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 70)
    log("#  crash_region_probe - what will the 900E handler actually give us?")
    log("=" * 70)

    deadline = time.time() + args.time
    link = tables = None
    while time.time() < deadline:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        log("  900E present - attempting MEMORY_DEBUG handshake")
        try:
            link, tables = handshake_memory_debug(dev)
        except Exception as err:  # noqa: BLE001
            log(f"  exception {type(err).__name__}: {err}")
            link = tables = None
        if tables:
            break
        try:
            usb.util.release_interface(dev, 0)
        except Exception:  # noqa: BLE001
            pass
        log("  no table - waiting for the next power cycle")
        # wait for the node to disappear so the next attempt gets a fresh one
        end = time.time() + 60
        while time.time() < end and usb.core.find(idVendor=0x05C6, idProduct=0x900E):
            time.sleep(0.05)
        link = tables = None

    if not tables:
        log("")
        log(">>> could not obtain the memory table (device busy / not in crashdump)")
        return 1

    log("")
    log(f"{'#':>3}  {'addr':>14}  {'len':>10}  {'pref':>4}  name")
    log("-" * 70)
    for i, e in enumerate(tables):
        log(f"{i:>3}  {e['addr']:#014x}  {e['len']:>10}  {e['pref']:>4}  "
            f"{e['file'] or e['desc']}")

    log("")
    log("=" * 70)
    log("#  content map (first 4 KiB of each entry)")
    log("=" * 70)
    interesting = []
    for e in tables:
        name = e["file"] or e["desc"] or f"entry{e['addr']:#x}"
        sample = mem_read(link, e["addr"], min(4096, e["len"]))
        verdict = classify(sample)
        log(f"{e['addr']:#014x} {name:<22s} {verdict}")
        if sample and not verdict.startswith(("0xFF fill", "all zeros")):
            interesting.append((name, e, sample))
            (OUT / f"sample_{e['addr']:#012x}_{name.replace('/', '_')}.bin").write_bytes(sample)

    # targeted grab
    grabs = []
    if args.grab:
        grabs = [e for e in tables if args.grab.lower() in (e["file"] or e["desc"]).lower()]
    elif args.full:
        grabs = [e for e in tables if e["len"] <= args.max]

    for e in grabs:
        name = e["file"] or e["desc"] or f"entry{e['addr']:#x}"
        log("")
        log(f"  grabbing {name} ({e['len']} B @ {e['addr']:#x})")
        blob = mem_read(link, e["addr"], e["len"], tmo=10.0)
        if blob:
            fn = OUT / f"full_{e['addr']:#012x}_{name.replace('/', '_')}"
            fn.write_bytes(blob)
            log(f"    {len(blob)} B -> {fn.name}")
        else:
            log("    no data")

    log("")
    log("=" * 70)
    log(f"entries: {len(tables)}   with real content: {len(interesting)}")
    log(f"files in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
