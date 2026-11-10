#!/usr/bin/env python3
"""sahara_exec_probe.py - ask the *boot ROM* what it knows, via Sahara EXECUTE.

Why this is new
---------------
Every previous session used Sahara mechanically: HELLO -> bump to 9008 -> upload
-> fail. The EXECUTE command class (0x0D) was used only for HWID and serial, and
then abandoned.

But the Sahara command set includes commands whose entire purpose is to report
target state:

    0x00 NOP
    0x01 SERIAL_NUM_READ
    0x02 MSM_HW_ID_READ
    0x03 OEM_PK_HASH_READ
    0x06 READ_DEBUG_DATA
    0x07 GET_SOFTWARE_VERSION_SBL
    0x08 GET_COMMAND_ID_LIST      <- which commands this PBL actually offers
    0x09 GET_TRAINING_DATA        <- **DDR training data**
    0x0A READ_CHIP_ID_V3

GET_TRAINING_DATA (0x09) is the interesting one. The melf carries a whole DDR
bring-up stage (`sbl1_ddr_init`, `do_ddr_training`). If DDR training is what
kills the Firehose programmer, the boot ROM is the component that ran that
training, and it may be able to report the result. That converts a hypothesis
into a measurement - or at least tells us the question is unanswerable from the
host, which is equally useful.

GET_COMMAND_ID_LIST (0x08) tells us whether any download mode we have not tried
is offered at all. If the list is shorter than the published set, some of our
"untried" ideas were never available in the first place.

Strictly read-only. Commands 0x04/0x05 (SWITCH_TO_*_DLOAD) are deliberately NOT
sent: they change state and one of them is a known dead end.

Usage
    python sahara_exec_probe.py
    python sahara_exec_probe.py --time 180
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

from crash_region_probe import Link, open_device  # noqa: E402

OUT = Path(__file__).resolve().parent / "sahara_exec_probe"
T0 = time.time()

CMD_HELLO_REQ = 0x01
CMD_HELLO_RSP = 0x02
CMD_RESET = 0x07
CMD_RESET_RSP = 0x08
CMD_CMD_READY = 0x0B
CMD_EXECUTE_REQ = 0x0D
CMD_EXECUTE_RSP = 0x0E
CMD_EXECUTE_DATA = 0x0F

MODE_COMMAND = 3
MODE_MEMORY_DEBUG = 2

EXEC = {
    0x00: ("NOP", "should echo immediately"),
    0x01: ("SERIAL_NUM_READ", "device serial"),
    0x02: ("MSM_HW_ID_READ", "hardware id, e.g. 0x2280e1"),
    0x03: ("OEM_PK_HASH_READ", "which OEM key the PBL trusts"),
    0x06: ("READ_DEBUG_DATA", "debug/training buffer"),
    0x07: ("GET_SOFTWARE_VERSION_SBL", "SBL build string"),
    0x08: ("GET_COMMAND_ID_LIST", "commands this PBL offers"),
    0x09: ("GET_TRAINING_DATA", "DDR training result"),
    0x0A: ("READ_CHIP_ID_V3", "extended chip info"),
}

# 0x04 / 0x05 intentionally absent: they switch download mode (state change).
SKIP = {0x04: "SWITCH_TO_DMSS_DLOAD", 0x05: "SWITCH_TO_STREAM_DLOAD"}

#: Sahara NAK codes, for reading the status field of END_TRANSFER.
NAK = {
    0x00: "SUCCESS", 0x01: "INVALID_CMD", 0x02: "PROTOCOL_MISMATCH",
    0x03: "INVALID_TARGET_PROTOCOL", 0x04: "INVALID_HOST_PROTOCOL",
    0x05: "INVALID_PACKET_SIZE", 0x06: "UNEXPECTED_IMAGE_ID",
    0x07: "INVALID_HEADER_SIZE", 0x08: "INVALID_DATA_SIZE",
    0x09: "INVALID_IMAGE_TYPE", 0x0A: "INVALID_TX_LENGTH",
    0x0B: "INVALID_RX_LENGTH", 0x0C: "GENERAL_TX_RX_ERROR",
    0x0D: "READ_DATA_ERROR", 0x0E: "UNSUPPORTED_NUM_PHDRS",
    0x0F: "INVALID_PDHR_SIZE", 0x10: "MULTIPLE_SHARED_SEG",
    0x11: "UNINIT_PHDR_LOC", 0x12: "INVALID_DEST_ADDR",
    0x13: "INVALID_IMG_HDR_DATA_SIZE", 0x14: "INVALID_ELF_HDR",
    0x15: "UNKNOWN_HOST_ERROR", 0x16: "TIMEOUT_RX", 0x17: "TIMEOUT_TX",
    0x18: "INVALID_HOST_MODE", 0x19: "INVALID_MEMORY_READ",
    0x1A: "INVALID_DATA_SIZE_REQUEST", 0x1B: "MEMORY_DEBUG_NOT_SUPPORTED",
    0x1C: "INVALID_MODE_SWITCH", 0x1D: "CMD_EXEC_FAILURE",
    0x1E: "EXEC_CMD_INVALID_PARAM", 0x1F: "EXEC_CMD_UNSUPPORTED",
    0x20: "EXEC_DATA_INVALID_CLIENT_CMD", 0x21: "HASH_TABLE_AUTH_FAILURE",
    0x22: "HASH_VERIFICATION_FAILURE", 0x23: "HASH_TABLE_NOT_FOUND",
    0x24: "TARGET_INIT_FAILURE", 0x25: "IMAGE_AUTH_FAILURE",
    0x26: "INVALID_IMG_HASH_TABLE_SIZE", 0x27: "ENUMERATION_FAILURE",
    0x28: "HW_BULK_TRANSFER_ERROR", 0x29: "VENDOR (not in published table)",
}


def log(msg: str = "") -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def enter_command_mode(link: Link) -> int | None:
    """HELLO -> HELLO_RSP(mode=COMMAND) -> CMD_READY. Returns Sahara version."""
    pkt = link.read_packet(3000)
    if pkt is None:
        log("  nothing pending -> SAHARA_RESET")
        link.write(struct.pack("<II", CMD_RESET, 8))
        pkt = link.read_packet(3000)
    if pkt is None:
        log("  device does not answer Sahara")
        return None

    cmd = struct.unpack_from("<I", pkt, 0)[0]
    if cmd == 0x04:  # END pending
        log("  END_TRANSFER pending -> SAHARA_RESET")
        link.write(struct.pack("<II", CMD_RESET, 8))
        pkt = link.read_packet(3000)
        if pkt is None:
            return None
        cmd = struct.unpack_from("<I", pkt, 0)[0]

    if cmd != CMD_HELLO_REQ:
        log(f"  expected HELLO, got {cmd:#x}")
        return None

    ver = struct.unpack_from("<I", pkt, 8)[0]
    mode = struct.unpack_from("<I", pkt, 20)[0]
    log(f"  HELLO ver={ver} mode={mode}")

    link.write(struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                           ver, 1, 0, MODE_COMMAND, 1, 2, 3, 4, 5, 6))
    rsp = link.read_packet(4000)
    if rsp is None:
        log("  no answer to HELLO_RSP(mode=3)")
        return None
    rcmd = struct.unpack_from("<I", rsp, 0)[0]
    if rcmd != CMD_CMD_READY:
        log(f"  expected CMD_READY (0x0B), got {rcmd:#x}")
        return None
    log("  CMD_READY - command mode accepted")
    return ver


def exec_cmd(link: Link, code: int, tmo: float = 2.5) -> bytes:
    """EXECUTE_REQ is {cmd, len, client_cmd}. Target answers EXECUTE_RSP with a length."""
    link.write(struct.pack("<III", CMD_EXECUTE_REQ, 12, code))
    rsp = link.read_packet(int(tmo * 1000))
    if rsp is None:
        return b""
    cmd = struct.unpack_from("<I", rsp, 0)[0]
    if cmd == CMD_EXECUTE_RSP:
        # {cmd, len, client_cmd, data_len}
        if len(rsp) >= 16:
            data_len = struct.unpack_from("<I", rsp, 12)[0]
            if data_len == 0:
                return b""
            data = link.read_packet(int(tmo * 1000))
            return data or b""
        return b""
    if cmd == CMD_EXECUTE_DATA:
        return rsp[8:] if len(rsp) > 8 else b""
    if cmd == 0x04 and len(rsp) >= 16:
        # END_TRANSFER {cmd, len, image_id, status} - the status is the answer
        status = struct.unpack_from("<I", rsp, 12)[0]
        log(f"    END_TRANSFER status={status:#04x} ({NAK.get(status, 'vendor/unknown')})")
        return b""
    log(f"    unexpected cmd {cmd:#x} for exec {code:#x}")
    return b""


def hexdump(blob: bytes, limit: int = 64) -> str:
    return blob[:limit].hex(" ")


def render(blob: bytes) -> str:
    if not blob:
        return "(no data)"
    parts = []
    printable = blob.split(b"\x00")[0]
    if len(printable) >= 4 and all(32 <= b < 127 for b in printable[:min(len(printable), 48)]):
        parts.append(f"ascii={printable[:64]!r}")
    if len(blob) >= 4:
        parts.append(f"u32[0]={struct.unpack_from('<I', blob, 0)[0]:#x}")
    if len(blob) >= 8:
        parts.append(f"u64[0]={struct.unpack_from('<Q', blob, 0)[0]:#x}")
    parts.append(f"hex={hexdump(blob)}")
    return "  ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=150.0)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 74)
    log("#  sahara_exec_probe - what does the boot ROM itself know?")
    log("=" * 74)

    ver = None
    deadline = time.time() + args.time
    while time.time() < deadline and ver is None:
        dev = open_device()
        if dev is None:
            time.sleep(0.05)
            continue
        try:
            link = Link(dev)
            ver = enter_command_mode(link)
        except Exception as err:  # noqa: BLE001
            log(f"  exception {type(err).__name__}: {err}")
            ver = None
        if ver is None:
            try:
                usb.util.release_interface(dev, 0)
            except Exception:  # noqa: BLE001
                pass
            end = time.time() + 60
            while time.time() < end and usb.core.find(idVendor=0x05C6, idProduct=0x900E):
                time.sleep(0.05)

    if ver is None:
        log(">>> could not enter command mode (device not answering or wedged)")
        return 1

    log("")
    log("-" * 74)
    log(f"#  EXECUTE commands (Sahara ver={ver})")
    log("-" * 74)

    results = {}
    for code in sorted(EXEC):
        name, why = EXEC[code]
        log("")
        log(f"  {code:#04x} {name}  -- {why}")
        try:
            blob = exec_cmd(link, code)
        except Exception as err:  # noqa: BLE001
            log(f"    exception {type(err).__name__}: {err}")
            continue
        results[code] = blob
        if blob:
            (OUT / f"exec_{code:02x}_{name}.bin").write_bytes(blob)
        log(f"    {len(blob):>5d} B  {render(blob)}")

        # decode the two that carry structure
        if code == 0x08 and blob:
            log("    command id list ->")
            for i in range(0, len(blob) - 3, 4):
                v = struct.unpack_from("<I", blob, i)[0]
                known = EXEC.get(v, (f"0x{v:02x}", ""))[0]
                log(f"      {v:#04x}  {known}")

    log("")
    log("-" * 74)
    log("#  commands deliberately not sent")
    log("-" * 74)
    for code, name in SKIP.items():
        log(f"  {code:#04x} {name} - changes download state, known dead end")

    # clean close so the next session starts from a fresh HELLO
    try:
        link.write(struct.pack("<II", CMD_RESET, 8))
        r = link.read_packet(3000)
        if r:
            log(f"  SAHARA_RESET -> {struct.unpack_from('<I', r, 0)[0]:#x}")
    except Exception:  # noqa: BLE001
        pass

    log("")
    log("=" * 74)
    log("#  SUMMARY")
    log("=" * 74)
    answered = [f"0x{c:02x} {EXEC[c][0]}" for c in sorted(results) if results[c]]
    silent = [f"0x{c:02x} {EXEC[c][0]}" for c in sorted(results) if not results[c]]
    log(f"  answered: {', '.join(answered) or 'none'}")
    log(f"  silent  : {', '.join(silent) or 'none'}")
    log(f"  artefacts in: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
