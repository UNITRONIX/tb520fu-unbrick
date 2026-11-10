#!/usr/bin/env python3
"""sahara_exec_9008.py - EXECUTE against the real PBL (9008, ver=3), not crashdump.

Why the distinction matters
---------------------------
sahara_exec_probe.py ran EXECUTE on 05C6:900E (Sahara ver=2, crashdump) and every
command came back rejected:

    0x00 NOP                 -> 0x1F EXEC_CMD_UNSUPPORTED
    0x01..0x0A everything    -> 0x01 INVALID_CMD

That is a property of the *crashdump handler*, not of the boot ROM. The notes
record that HWID 0x2280e1 was obtained via EXECUTE 0x02 in a 9008 session, so
the real PBL does implement this command class. Testing on 900E therefore proves
nothing about what the PBL will answer.

This script does it in the right state: bump 900E -> 9008, then EXECUTE.

The one command that matters here is 0x09 GET_TRAINING_DATA. The melf carries a
full DDR bring-up stage (`sbl1_ddr_init`, `do_ddr_training`) and the Firehose
programmer never starts. If the PBL will report its DDR training outcome, the
"programmer dies in DDR init" hypothesis becomes measurable. 0x08
GET_COMMAND_ID_LIST tells us which of these are offered at all.

Read-only against the target: EXECUTE requests do not write storage and do not
change download mode (0x04 / 0x05 are deliberately never sent).

Usage
    python sahara_exec_9008.py
    python sahara_exec_9008.py --time 240
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

OUT = Path(__file__).resolve().parent / "sahara_exec_9008"
T0 = time.time()

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_END_TRANSFER = 0x04
CMD_DONE_REQ = 0x05
CMD_DONE_RSP = 0x06
CMD_RESET = 0x07
CMD_CMD_READY = 0x0B
CMD_SWITCH_MODE = 0x0C
CMD_EXECUTE_REQ = 0x0D
CMD_EXECUTE_RSP = 0x0E
CMD_EXECUTE_DATA = 0x0F

MODE_IMAGE_TX = 0
MODE_COMMAND = 3

NAK = {
    0x00: "SUCCESS", 0x01: "INVALID_CMD", 0x1D: "CMD_EXEC_FAILURE",
    0x1E: "EXEC_CMD_INVALID_PARAM", 0x1F: "EXEC_CMD_UNSUPPORTED",
    0x20: "EXEC_DATA_INVALID_CLIENT_CMD", 0x1C: "INVALID_MODE_SWITCH",
}

EXEC = {
    0x09: "GET_TRAINING_DATA",
    0x08: "GET_COMMAND_ID_LIST",
    0x02: "MSM_HW_ID_READ",
    0x01: "SERIAL_NUM_READ",
    0x0A: "READ_CHIP_ID_V3",
    0x07: "GET_SOFTWARE_VERSION_SBL",
    0x03: "OEM_PK_HASH_READ",
    0x06: "READ_DEBUG_DATA",
    0x00: "NOP",
}


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def find(pid: int):
    return usb.core.find(idVendor=0x05C6, idProduct=pid)


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


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def bump(link: Link) -> bool:
    """900E (mode=2) -> 9008 (mode=0). Sequence from docs/14, 12-byte switch."""
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
        log(f"  bump: expected HELLO, got {cmd:#x}")
        return False

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  bump: HELLO ver={ver} mode={mode}")
    if mode == MODE_IMAGE_TX:
        log("  bump: already IMAGE_TX - no switch needed")
        return True

    link.write(hello_rsp(ver, MODE_COMMAND))
    r = link.read_packet(3000)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
        log(f"  bump: no CMD_READY ({'none' if r is None else hex(struct.unpack_from('<I', r, 0)[0])})")
        return False

    link.write(struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX))
    r = link.read_packet(4000)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
        log("  bump: switch not confirmed by a fresh HELLO")
        return False

    link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
    r = link.read_packet(4000)
    if r is None:
        log("  bump: no answer after confirm")
        return False
    if struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
        status = struct.unpack_from("<I", r, 12)[0] if len(r) >= 16 else -1
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        link.read_packet(3000)
        log(f"  bump: END status={status:#x} -> DONE sent")
    log("  bump: switch done, waiting for 9008")
    return True


def wait_for(pid: int, budget: float) -> bool:
    end = time.time() + budget
    while time.time() < end:
        if find(pid) is not None:
            time.sleep(0.1)
            return True
        time.sleep(0.05)
    return False


def enter_command_mode(link: Link):
    pkt = link.read_packet(4000)
    if pkt is None:
        log("  no HELLO on 9008")
        return None
    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO, got {cmd:#x}")
        return None
    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  HELLO ver={ver} mode={mode}")
    if mode != MODE_IMAGE_TX:
        log(f"  mode={mode} is not IMAGE_TX (0) - not the state we want")
        return None
    link.write(hello_rsp(ver, MODE_COMMAND))
    r = link.read_packet(4000)
    if r is None:
        return None
    rcmd = struct.unpack_from("<I", r, 0)[0]
    if rcmd != CMD_CMD_READY:
        if rcmd == CMD_END_TRANSFER:
            st = struct.unpack_from("<I", r, 12)[0] if len(r) >= 16 else -1
            log(f"  refused command mode: {st:#x} {NAK.get(st, '')}")
        else:
            log(f"  expected CMD_READY, got {rcmd:#x}")
        return None
    log("  CMD_READY (command mode accepted on the real PBL)")
    return ver


def read_raw(link: Link, n: int, tmo: float = 3.0) -> bytes:
    """Read exactly n raw bytes. EXECUTE responses are payload, not Sahara packets."""
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


def exec_cmd(link: Link, code: int, tmo: float = 3.0) -> tuple[bytes, str]:
    """Full EXECUTE exchange, matching edlclient's cmd_exec.

    EXECUTE_REQ  {cmd, len, client_cmd}
    EXECUTE_RSP  {cmd, len, client_cmd, data_len}   <- data_len is the payload size
    EXECUTE_DATA {cmd, len, client_cmd}             <- host acknowledges
    then data_len RAW bytes, NOT a Sahara packet. Getting this wrong desynchronises
    the session and every later command looks silent - which is exactly what the
    first version of this script hit.
    """
    link.write(struct.pack("<III", CMD_EXECUTE_REQ, 12, code))
    rsp = link.read_packet(int(tmo * 1000))
    if rsp is None:
        return b"", "no response"
    cmd = struct.unpack_from("<I", rsp, 0)[0]

    if cmd == CMD_EXECUTE_RSP and len(rsp) >= 16:
        data_len = struct.unpack_from("<I", rsp, 12)[0]
        link.write(struct.pack("<III", CMD_EXECUTE_DATA, 12, code))
        if data_len == 0:
            return b"", "accepted, no data"
        if data_len > (1 << 20):
            return b"", f"implausible data_len {data_len}"
        data = read_raw(link, data_len, tmo)
        return data, f"ok ({data_len} B)"
    if cmd == CMD_EXECUTE_DATA:
        return rsp[8:], "ok (data-first)"
    if cmd == CMD_END_TRANSFER and len(rsp) >= 16:
        st = struct.unpack_from("<I", rsp, 12)[0]
        return b"", f"END status={st:#04x} {NAK.get(st, 'vendor/unknown')}"
    return b"", f"unexpected cmd {cmd:#x}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=200.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 74)
    log("#  sahara_exec_9008 - EXECUTE on the real PBL (ver=3)")
    log("=" * 74)

    deadline = time.time() + args.time
    link = None

    while time.time() < deadline and link is None:
        # A stale 9008 is common after an aborted transfer and is mute. Only
        # trust it if it actually answers a HELLO.
        if find(0x9008) is not None:
            dev = open_pid(0x9008)
            if dev is not None:
                try:
                    probe = Link(dev)
                    if probe.read_packet(2500) is not None:
                        link = probe
                        log("  using an already-present, responsive 9008")
                        break
                    log("  9008 present but mute (zombie) - will cycle it")
                except Exception:  # noqa: BLE001
                    log("  9008 present but unopenable - will cycle it")
                try:
                    usb.util.release_interface(dev, 0)
                except Exception:  # noqa: BLE001
                    pass
        dev = open_pid(0x900E)
        if dev is None:
            time.sleep(0.05)
            continue
        log("  900E present - bumping")
        try:
            l2 = Link(dev)
            if bump(l2):
                if wait_for(0x9008, 40):
                    link = Link(open_pid(0x9008))
                    log("  9008 is up")
                    break
                log("  9008 did not appear within 40 s")
        except Exception as err:  # noqa: BLE001
            log(f"  bump exception {type(err).__name__}: {err}")
        end = time.time() + 50
        while time.time() < end and find(0x900E) is not None:
            time.sleep(0.05)

    if link is None:
        log(">>> never reached 9008")
        return 1

    ver = enter_command_mode(link)
    if ver is None:
        log(">>> could not enter command mode on the PBL")
        return 1

    log("")
    log("-" * 74)
    log(f"#  EXECUTE probes (PBL ver={ver})")
    log("-" * 74)
    results = {}
    for code, name in EXEC.items():
        data, note = exec_cmd(link, code)
        results[code] = (data, note)
        if data:
            (OUT / f"exec_{code:02x}_{name}.bin").write_bytes(data)
        rendered = ""
        if data:
            if len(data) >= 4:
                rendered += f" u32={struct.unpack_from('<I', data, 0)[0]:#x}"
            if len(data) >= 8:
                rendered += f" u64={struct.unpack_from('<Q', data, 0)[0]:#x}"
            txt = data.split(b"\x00")[0]
            if len(txt) >= 4 and all(32 <= b < 127 for b in txt[:min(32, len(txt))]):
                rendered += f" ascii={txt[:64]!r}"
        log(f"  {code:#04x} {name:<24s} {len(data):>5d} B  {note}{rendered}")

        # Any rejected EXECUTE can push the target out of command mode. Re-enter
        # rather than letting the remaining probes report false silence.
        if not data and "END status" in note:
            log("      (out of command mode - re-entering)")
            try:
                if enter_command_mode(link) is None:
                    log("      could not re-enter; remaining probes unreliable")
                    break
            except Exception as err:  # noqa: BLE001
                log(f"      re-enter failed: {type(err).__name__}")
                break

    # decode the command id list if we got one
    data, note = results.get(0x08, (b"", ""))
    if data:
        log("")
        log("  command id list:")
        for i in range(0, len(data) - 3, 4):
            v = struct.unpack_from("<I", data, i)[0]
            log(f"    {v:#04x}  {EXEC.get(v, 'not in our table')}")

    try:
        link.write(struct.pack("<II", CMD_RESET, 8))
        link.read_packet(3000)
    except Exception:  # noqa: BLE001
        pass

    log("")
    log("=" * 74)
    ok = [f"{EXEC[c]}" for c in results if results[c][0]]
    no = [f"{EXEC[c]} ({results[c][1]})" for c in results if not results[c][0]]
    log(f"  answered: {', '.join(ok) or 'none'}")
    log(f"  refused : {'; '.join(no) or 'none'}")
    log(f"  artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
