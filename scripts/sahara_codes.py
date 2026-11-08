#!/usr/bin/env python3
"""
sahara_codes.py - Sahara command and NAK code tables.

Values 0x01-0x28 are from the public Qualcomm Sahara protocol as implemented by
edlclient (see references). Values above 0x28 are NOT in the published table: this
device returned 0x29, which is a vendor extension. It is marked as such rather
than guessed at.

Use as a library:
    from sahara_codes import CMD, NAK, describe_nak
    describe_nak(0x29)   -> "VENDOR NAK (not in published table) ..."

Or as a CLI:
    python sahara_codes.py            print the full table
    python sahara_codes.py 0x21       explain one code
"""

from __future__ import annotations

import sys


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
CMD = {
    0x01: "HELLO_REQ",              # device -> host
    0x02: "HELLO_RSP",              # host -> device
    0x03: "READ_DATA",              # device -> host
    0x04: "END_TRANSFER",           # device -> host
    0x05: "DONE_REQ",               # host -> device
    0x06: "DONE_RSP",               # device -> host
    0x07: "SAHARA_RESET",           # host -> device  (use this one)
    0x08: "RESET_RSP",              # device -> host
    0x09: "MEMORY_DEBUG",           # host -> device
    0x0A: "MEMORY_READ_DATA",       # device -> host
    0x0B: "CMD_READY",              # device -> host
    0x0C: "CMD_EXECUTE",            # host -> device
    0x0D: "CMD_EXECUTE_RSP",        # device -> host
    0x0E: "CMD_EXECUTE_DATA",       # device -> host
    0x0F: "MEMORY_DEBUG_64",        # host -> device
    0x10: "MEMORY_READ_DATA_64",    # device -> host
    0x11: "CMD_READY_64",           # device -> host
    0x12: "64BIT_MEMORY_READ_DATA", # device -> host
    0x13: "RESET_STATE_MACHINE",    # host -> device  (DESTRUCTIVE, see below)
}

#: Commands that must never be sent casually.
DANGEROUS = {
    0x13: (
        "RESET_STATE_MACHINE terminates the session in a way that leaves the "
        "endpoint unusable. The next attempt has nothing to talk to. Observed on "
        "TB520FU: causes a pipe error. Use SAHARA_RESET (0x07) instead."
    ),
}


# ---------------------------------------------------------------------------
# NAK codes 0x01-0x28 (published table)
# ---------------------------------------------------------------------------
NAK = {
    0x01: "NAK_INVALID_CMD",
    0x02: "NAK_PROTOCOL_MISMATCH",
    0x03: "NAK_INVALID_TARGET_PROTOCOL",
    0x04: "NAK_INVALID_HOST_PROTOCOL",
    0x05: "NAK_INVALID_PACKET_SIZE",
    0x06: "NAK_UNEXPECTED_IMAGE_ID",
    0x07: "NAK_INVALID_HEADER_SIZE",
    0x08: "NAK_INVALID_DATA_SIZE",
    0x09: "NAK_INVALID_IMAGE_TYPE",
    0x0A: "NAK_INVALID_TX_LENGTH",
    0x0B: "NAK_INVALID_RX_LENGTH",
    0x0C: "NAK_GENERAL_TX_RX_ERROR",
    0x0D: "NAK_READ_DATA_ERROR",
    0x0E: "NAK_UNSUPPORTED_NUM_PHDRS",
    0x0F: "NAK_INVALID_PDHR_SIZE",
    0x10: "NAK_MULTIPLE_SHARED_SEG",
    0x11: "NAK_UNINIT_PHDR_LOC",
    0x12: "NAK_INVALID_DEST_ADDR",
    0x13: "NAK_INVALID_IMG_HDR_DATA_SIZE",
    0x14: "NAK_INVALID_ELF_HDR",
    0x15: "NAK_UNKNOWN_HOST_ERROR",
    0x16: "NAK_TIMEOUT_RX",
    0x17: "NAK_TIMEOUT_TX",
    0x18: "NAK_INVALID_HOST_MODE",
    0x19: "NAK_INVALID_MEMORY_READ",
    0x1A: "NAK_INVALID_DATA_SIZE_REQUEST",
    0x1B: "NAK_MEMORY_DEBUG_NOT_SUPPORTED",
    0x1C: "NAK_INVALID_MODE_SWITCH",
    0x1D: "NAK_CMD_EXEC_FAILURE",
    0x1E: "NAK_EXEC_CMD_INVALID_PARAM",
    0x1F: "NAK_EXEC_CMD_UNSUPPORTED",
    0x20: "NAK_EXEC_DATA_INVALID_CLIENT_CMD",
    0x21: "NAK_HASH_TABLE_AUTH_FAILURE",
    0x22: "NAK_HASH_VERIFICATION_FAILURE",
    0x23: "NAK_HASH_TABLE_NOT_FOUND",
    0x24: "NAK_TARGET_INIT_FAILURE",
    0x25: "NAK_IMAGE_AUTH_FAILURE",
    0x26: "NAK_INVALID_IMG_HASH_TABLE_SIZE",
    0x27: "NAK_ENUMERATION_FAILURE",
    0x28: "NAK_HW_BULK_TRANSFER_ERROR",
}

#: Longer explanations, with what the code actually meant on TB520FU.
NOTES = {
    0x0D: (
        "Observed on TB520FU purely as a symptom of a broken packet stream: the "
        "host was parsing only the first Sahara packet out of each read() and "
        "discarding the rest. Fix the framing before believing this code means "
        "anything about the device."
    ),
    0x21: (
        "On TB520FU this appeared when an image inside the melf container was "
        "replaced. The transfer died at byte 1 109 804, which is BEFORE the "
        "modified image at 1 117 008 -- so the check covers the whole blob, not "
        "per-image. There is no per-image digest stored in the file under any "
        "standard algorithm (see docs/04-melf-format.md section 5), and one "
        "652-byte metadata blob in the wrapper was never decoded."
    ),
    0x23: (
        "Returned for a plain ELF with no MBN hash segment. This is what made "
        "qtestsign look promising (it adds exactly that segment), but the payload "
        "had already been rejected at 64 bytes, so the hash table was never "
        "consulted."
    ),
    0x29: (
        "NOT IN THE PUBLISHED TABLE. Vendor extension. On TB520FU it was returned "
        "after exactly 64 bytes -- the size of the header Sahara reads to classify "
        "a payload. It means 'I cannot parse this container': a plain ELF64 is "
        "rejected regardless of signing. The same code arrives for the device's "
        "own prog_firehose_ddr.elf, confirming it is about format."
    ),
}

#: Highest value in the published table.
NAK_MAX_PUBLISHED = 0x28


def describe_nak(code: int, verbose: bool = True) -> str:
    """Return a human-readable explanation of a NAK code."""
    if code in NAK:
        name = NAK[code]
        line = f"0x{code:02X}  {name}"
        if verbose and code in NOTES:
            line += f"\n      {NOTES[code]}"
        return line
    if code > NAK_MAX_PUBLISHED:
        line = (f"0x{code:02X}  VENDOR NAK (not in the published table, "
                f"which ends at 0x{NAK_MAX_PUBLISHED:02X})")
        if verbose and code in NOTES:
            line += f"\n      {NOTES[code]}"
        elif verbose:
            line += ("\n      Treat as a manufacturer-specific rejection. Infer its "
                     "meaning from WHEN it is returned: the byte offset of the "
                     "rejection tells you which check failed.")
        return line
    return f"0x{code:02X}  <unknown / reserved>"


def describe_cmd(code: int) -> str:
    name = CMD.get(code, "<unknown>")
    line = f"0x{code:02X}  {name}"
    if code in DANGEROUS:
        line += f"\n      WARNING: {DANGEROUS[code]}"
    return line


def print_all() -> None:
    print("=" * 72)
    print("SAHARA COMMANDS")
    print("=" * 72)
    for code in sorted(CMD):
        print(describe_cmd(code))
    print()
    print("=" * 72)
    print("SAHARA NAK CODES (0x01-0x28 published; above is vendor territory)")
    print("=" * 72)
    for code in sorted(NAK):
        print(describe_nak(code, verbose=False))
    print()
    print("Vendor codes seen on TB520FU:")
    print(describe_nak(0x29))
    print()
    print("--- notes on the codes that mattered most ---")
    for code in (0x0D, 0x21, 0x23, 0x29):
        print()
        print(describe_nak(code))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print_all()
        return 0
    raw = argv[1]
    try:
        code = int(raw, 0)
    except ValueError:
        print(f"not a number: {raw!r}  (try 0x21 or 33)")
        return 2
    print(describe_nak(code))
    if code in CMD:
        print()
        print("also a command:")
        print(describe_cmd(code))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
