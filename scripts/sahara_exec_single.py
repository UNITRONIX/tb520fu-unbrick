#!/usr/bin/env python3
"""sahara_exec_single.py - one EXECUTE command per fresh power cycle.

Why single-shot
---------------
sahara_exec_9008.py sent nine EXECUTE commands in one session. The first one
(GET_TRAINING_DATA) was rejected with END_TRANSFER 0x1F, and that rejection drops
the target out of command mode - so every later probe reported "no response" for
a reason that had nothing to do with the command being tested. The result was one
real data point and eight meaningless ones.

This script removes the confound: it performs exactly ONE EXECUTE per Sahara
session, on a freshly enumerated 900E, then lets the device cycle and starts
over for the next command.

What it is looking for
----------------------
0x08 GET_COMMAND_ID_LIST tells us which download modes this PBL implements at
all. That matters because the entire recovery effort assumed Firehose is the only
path, and Firehose is the thing that hangs. Sahara also defines:

    0x04 SWITCH_TO_DMSS_DLOAD
    0x05 SWITCH_TO_STREAM_DLOAD

Neither requires the Firehose programmer. docs/14-edl-mode-switch.md records them
as "no useful effect" - but that test was run in crashdump mode (900E, ver=2),
where every EXECUTE is rejected anyway (measured: 0x1F / 0x01). They have never
been tried against the real PBL (9008, ver=3).

If the PBL answers 0x08 with a list containing 0x04 or 0x05, there is a download
path that does not involve the component that hangs. That is worth knowing before
anyone pays for a mainboard.

State-changing commands are opt-in via --allow-dload, because they can leave the
device in a state that needs a manual power cycle.

Usage
    python sahara_exec_single.py                 # informative commands only
    python sahara_exec_single.py --allow-dload   # also try 0x04 / 0x05
    python sahara_exec_single.py --only 0x08
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crash_region_probe import Link  # noqa: E402

T0 = time.time()

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_RESET = 0x07
CMD_CMD_READY = 0x0B
CMD_SWITCH_MODE = 0x0C
CMD_EXECUTE_REQ = 0x0D
CMD_EXECUTE_RSP = 0x0E
CMD_EXECUTE_DATA = 0x0F

MODE_IMAGE_TX = 0
MODE_COMMAND = 3

NAK = {
    0x00: "SUCCESS", 0x01: "INVALID_CMD", 0x1C: "INVALID_MODE_SWITCH",
    0x1D: "CMD_EXEC_FAILURE", 0x1E: "EXEC_CMD_INVALID_PARAM",
    0x1F: "EXEC_CMD_UNSUPPORTED", 0x20: "EXEC_DATA_INVALID_CLIENT_CMD",
}

#: Read-only / informative probes, in priority order.
SAFE = [
    (0x08, "GET_COMMAND_ID_LIST"),
    (0x02, "MSM_HW_ID_READ"),
    (0x0A, "READ_CHIP_ID_V3"),
    (0x07, "GET_SOFTWARE_VERSION_SBL"),
    (0x03, "OEM_PK_HASH_READ"),
    (0x01, "SERIAL_NUM_READ"),
    (0x00, "NOP"),
]

#: State-changing: these may switch the download protocol.
DLOAD = [
    (0x05, "SWITCH_TO_STREAM_DLOAD"),
    (0x04, "SWITCH_TO_DMSS_DLOAD"),
]


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def find(pid: int):
    return usb.core.find(idVendor=0x05C6, idProduct=pid)


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def open_pid(pid: int):
    dev = find(pid)
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


def wait_absent(budget: float = 80.0) -> bool:
    """Wait until no Qualcomm node is present, i.e. the device has cycled."""
    end = time.time() + budget
    while time.time() < end:
        if find(0x900E) is None and find(0x9008) is None:
            return True
        time.sleep(0.05)
    return False


def wait_900e(budget: float = 90.0) -> bool:
    end = time.time() + budget
    while time.time() < end:
        if find(0x900E) is not None:
            time.sleep(0.15)
            return True
        time.sleep(0.05)
    return False


def is_zombie_9008() -> bool:
    """A 9008 node can be present in PnP and permanently mute.

    docs/05-firehose-and-the-silence.md section 3 documents this state: the node
    enumerates, is unusable, and only a manual power cycle clears it. Detect it
    explicitly, because waiting for such a node to disappear waits forever.
    """
    if find(0x9008) is None:
        return False
    dev = open_pid(0x9008)
    if dev is None:
        return True
    try:
        return Link(dev).read_packet(2000) is None
    except Exception:  # noqa: BLE001
        return True


def fresh_cycle(budget: float = 150.0) -> bool:
    """Force a genuinely NEW 900E.

    A 900E left over from a previous session answers `END_TRANSFER` or throws
    USBTimeoutError on the first write, because the previous EXECUTE rejection
    left it mid-state. Only a node that has left the bus and come back is usable,
    so this always waits for an absence transition first.
    """
    if is_zombie_9008():
        log("  !! zombie 9008 present: enumerable but mute.")
        log("  !! Only a manual power cycle (hold Power ~15 s) clears this.")
        return False

    # 1. wait for the device to leave the bus (it power-cycles on its own)
    if not wait_absent(budget):
        log("  device never left the bus - cannot guarantee a fresh session")
        return False
    # 2. wait for the new 900E
    return wait_900e(budget)


def bump(link: Link) -> bool:
    pkt = link.read_packet(3000)
    if pkt is None:
        link.write(struct.pack("<II", CMD_RESET, 8))
        pkt = link.read_packet(3000)
    if pkt is None:
        return False
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd == CMD_END_TRANSFER:
        link.write(struct.pack("<II", CMD_RESET, 8))
        pkt = link.read_packet(3000)
        if pkt is None:
            return False
        cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        return False

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    if mode == MODE_IMAGE_TX:
        return True
    link.write(hello_rsp(ver, MODE_COMMAND))
    r = link.read_packet(3000)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
        return False
    link.write(struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX))
    r = link.read_packet(4000)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
        return False
    link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
    r = link.read_packet(4000)
    if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        link.read_packet(2500)
    return True


def read_raw(link: Link, n: int, tmo: float = 3.0) -> bytes:
    out = b""
    if link.buf:
        out, link.buf = link.buf[:n], link.buf[n:]
    deadline = time.time() + tmo
    while len(out) < n and time.time() < deadline:
        try:
            b = link._fill(200)
        except Exception:  # noqa: BLE001
            break
        if b:
            out += b
    return out[:n]


def one_probe(code: int, name: str) -> tuple[bytes, str]:
    """Enter a fresh 9008 and issue exactly one EXECUTE."""
    log("")
    log(f"===== {code:#04x} {name} =====")

    if not fresh_cycle():
        return b"", "no fresh 900E cycle"

    dev = open_pid(0x900E)
    if dev is None:
        return b"", "900E vanished"
    if not bump(Link(dev)):
        return b"", "bump failed"
    log("  bump ok, waiting for 9008")
    t = time.time() + 45
    while time.time() < t and find(0x9008) is None:
        time.sleep(0.05)
    if find(0x9008) is None:
        return b"", "9008 never appeared"

    dev = open_pid(0x9008)
    if dev is None:
        return b"", "9008 unopenable"
    link = Link(dev)

    pkt = link.read_packet(4000)
    if pkt is None:
        return b"", "9008 mute"
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        return b"", f"expected HELLO, got {cmd:#x}"
    ver = struct.unpack_from("<I", pkt, 8)[0]
    log(f"  HELLO ver={ver} mode={struct.unpack_from('<I', pkt, 20)[0]}")

    link.write(hello_rsp(ver, MODE_COMMAND))
    r = link.read_packet(4000)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
        got = "none" if r is None else hex(struct.unpack_from("<I", r, 0)[0])
        return b"", f"command mode refused ({got})"
    log("  CMD_READY")

    link.write(struct.pack("<III", CMD_EXECUTE_REQ, 12, code))
    rsp = link.read_packet(4000)
    if rsp is None:
        return b"", "no EXECUTE response"

    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    if rcmd == CMD_EXECUTE_RSP and len(rsp) >= 16:
        data_len = struct.unpack_from("<I", rsp, 12)[0]
        link.write(struct.pack("<III", CMD_EXECUTE_DATA, 12, code))
        if data_len == 0:
            return b"", "accepted, zero-length"
        if data_len > (1 << 20):
            return b"", f"implausible len {data_len}"
        return read_raw(link, data_len), f"ok ({data_len} B)"
    if rcmd == CMD_END_TRANSFER and len(rsp) >= 16:
        st = struct.unpack_from("<I", rsp, 12)[0]
        return b"", f"END {st:#04x} {NAK.get(st, 'vendor')}"
    return b"", f"unexpected cmd {rcmd:#x}"


def render(data: bytes) -> str:
    if not data:
        return ""
    parts = []
    if len(data) >= 4:
        parts.append(f"u32[0]={struct.unpack_from('<I', data, 0)[0]:#x}")
    if len(data) >= 8:
        parts.append(f"u64[0]={struct.unpack_from('<Q', data, 0)[0]:#x}")
    txt = data.split(b"\x00")[0]
    if len(txt) >= 3 and all(32 <= b < 127 for b in txt[:min(24, len(txt))]):
        parts.append(f"ascii={txt[:60]!r}")
    parts.append(f"hex={data[:24].hex(' ')}")
    return "  ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-dload", action="store_true",
                    help="also try the state-changing SWITCH_TO_*_DLOAD commands")
    ap.add_argument("--only", default=None, help="single command, hex")
    args = ap.parse_args()

    todo = list(SAFE)
    if args.allow_dload:
        todo += list(DLOAD)
    if args.only:
        c = int(args.only, 0)
        todo = [(c, dict(SAFE + DLOAD).get(c, "custom"))]

    log("=" * 74)
    log("#  sahara_exec_single - one EXECUTE per fresh session")
    log("=" * 74)

    results = {}
    for code, name in todo:
        try:
            data, note = one_probe(code, name)
        except Exception as err:  # noqa: BLE001
            data, note = b"", f"exception {type(err).__name__}: {err}"
        results[code] = (name, data, note)
        log(f"  RESULT {code:#04x} {name:<24s} {len(data):>5d} B  {note}")
        if data:
            log(f"         {render(data)}")

        # decode the command list if that is what we got
        if code == 0x08 and data:
            log("         command ids offered by this PBL:")
            for i in range(0, len(data) - 3, 4):
                v = struct.unpack_from("<I", data, i)[0]
                known = dict(SAFE + DLOAD).get(v)
                log(f"           {v:#04x}  {known or 'not in our table'}")

    log("")
    log("=" * 74)
    log("#  SUMMARY")
    log("=" * 74)
    for code in sorted(results):
        name, data, note = results[code]
        log(f"  {code:#04x} {name:<24s} {len(data):>5d} B  {note}")

    ok = [n for c, (n, d, _) in results.items() if d]
    log("")
    log(f"  answered: {', '.join(ok) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
