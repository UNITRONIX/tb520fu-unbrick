#!/usr/bin/env python3
"""Peek small DDR windows in 900E - can we read the RUNNING ABL's decrypted code?

Why this matters
----------------
abl_signed-SM8650.elf is packed: entropy 7.97 bit/B, zero strings, no known
container format. It cannot be analysed or patched as a file.

But the ABL clearly RUNS: the tablet draws the offline-charging battery screen.
A running UEFI image is decrypted/unpacked in RAM. The ELF header tells us where:

    ph[2] type=LOAD  p_vaddr = 0x9fa00000  filesz = 249856

DDR CS0 begins at 0x80000000, so the ABL's code should sit around
0x9fa00000 once loaded. DRAM keeps its contents across a watchdog reset
(refresh continues), and the crashdump handler runs from AOP - so the bytes
may still be readable.

Earlier sessions declared DDR unreadable, but always with the 2 GB table
entries (they were filtered out or timed out). Nobody tried a 4 KB window.
That is the whole point of this script.

If we get readable code we can find the key/menu logic and stop guessing
about GPIO mapping.

Read-only. Small chunks only, because a 900E session lives ~9.9 s.

Usage
    python ddr_peek.py
    python ddr_peek.py --addr 0x9fa00000 --len 4096
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core

KIT = Path(__file__).resolve().parent
EDL_TOOLS = Path(r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\edl-tools")
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(EDL_TOOLS))

from edlclient.Library.Connection.usblib import usb_class  # noqa: E402
from edlclient.Library.sahara import sahara  # noqa: E402
from edlclient.Library.sahara_defs import cmd_t, sahara_mode_t  # noqa: E402

OUT = KIT / "ddr_peek"
T0 = time.time()

# ABL load address from its own ELF program header, plus a few sanity probes.
PROBES = [
    (0x9FA00000, 4096, "ABL code (ELF p_vaddr)"),
    (0x9FA02000, 4096, "ABL code +0x2000"),
    (0x9FA3D000, 4096, "ABL hash segment (paddr)"),
    (0x80000000, 4096, "DDR CS0 start"),
    (0x80100000, 4096, "DDR CS0 +16M"),
    (0x9F000000, 4096, "DDR below ABL"),
]


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.2f}] {msg}", flush=True)


def find(pid: int):
    return usb.core.find(idVendor=0x05C6, idProduct=pid)


def connect(pid: int):
    cdc = usb_class(portconfig=[[0x05C6, pid, -1]], loglevel=50)
    try:
        if not cdc.connect(EP_IN=-1, EP_OUT=-1):
            return None, None
    except Exception as err:  # noqa: BLE001
        log(f"connect exc {type(err).__name__}")
        return None, None
    return cdc, sahara(cdc, loglevel=50)


def parse_table(payload: bytes) -> list[dict]:
    out, ENT, off = [], 64, 0
    while off + ENT <= len(payload):
        _pref, base, length = struct.unpack_from("<QQQ", payload, off)
        desc = payload[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
        fname = payload[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
        if length == 0 or length > (1 << 34):
            break
        out.append({"addr": base, "len": length, "desc": desc, "file": fname or desc})
        off += ENT
    return out


def mem_read(cdc, addr: int, length: int, tmo: float = 1.2) -> bytes:
    pkt = struct.pack("<IIQQ", cmd_t.SAHARA_64BIT_MEMORY_READ,
                      0x08 + 8 + 8, addr, length)
    try:
        if not cdc.write(pkt):
            return b""
    except Exception:  # noqa: BLE001
        return b""
    got = bytearray()
    deadline = time.time() + tmo
    while len(got) < length and time.time() < deadline:
        try:
            n = bytes(cdc.usbread(min(cdc.maxsize, length - len(got)), 120))
        except Exception:  # noqa: BLE001
            break
        if not n:
            continue
        got += n
    return bytes(got)


def classify(blob: bytes) -> str:
    if not blob:
        return "pusty / brak odpowiedzi"
    nz = sum(1 for x in blob if x)
    head = blob[:16]
    if head[:4] == b"\x7fELF":
        return "*** ELF! ***"
    if nz == 0:
        return "same zera"
    if all(x == 0xFF for x in head):
        return "0xFF fill -> adres NIEZAMAPOWANY"
    # AArch64 opcodes never sit in the 0xE0-0xFF top-6-bit band for real code
    words = struct.unpack_from(f"<{len(blob)//4}I", blob, 0)
    plausible = sum(1 for w in words if (w >> 26) < 0x3C and w not in (0, 0xFFFFFFFF))
    ratio = plausible / max(1, len(words))
    density = nz / len(blob)
    tag = "kod/ARM64-podobne" if ratio > 0.85 and density > 0.4 else "dane"
    return f"{tag} (nonzero {density:.0%}, ARM64-like {ratio:.0%}), head={head.hex(' ')}"


def session(addr: int, length: int, label: str) -> bytes:
    """One short 900E session, one read."""
    cdc, sh = connect(0x900E)
    if not cdc:
        return b""
    try:
        r = sh.connect()
        if not isinstance(r, dict) or r.get("cmd") != cmd_t.SAHARA_HELLO_REQ:
            return b""
        ver, mode = r["data"].version, r["data"].mode
        if mode != 2:
            log(f"  mode={mode} (nie crashdump)")
            return b""
        cdc.write(struct.pack("<IIIIIIIIIIII", cmd_t.SAHARA_HELLO_RSP, 0x30,
                              ver, 1, 0, sahara_mode_t.SAHARA_MODE_MEMORY_DEBUG,
                              1, 2, 3, 4, 5, 6))
        r = sh.get_rsp()
        if not isinstance(r, dict) or r.get("cmd") not in (
                cmd_t.SAHARA_MEMORY_DEBUG, cmd_t.SAHARA_64BIT_MEMORY_DEBUG):
            return b""
        # handshake done; now the direct read
        log(f"  {label}: czytam {length} B z {addr:#x}")
        blob = mem_read(cdc, addr, length)
        return blob
    except Exception as err:  # noqa: BLE001
        log(f"  exc {type(err).__name__}")
        return b""
    finally:
        try:
            cdc.close()
        except Exception:  # noqa: BLE001
            pass


def wait_fresh_900e(budget: float) -> bool:
    """Wait for a FRESH 900E: it must disappear and come back.

    A 900E left over from a failed session answers `Device is in Sahara error
    state` and can never be read. Only a new power cycle gives a usable node.
    """
    end = time.time() + budget
    # phase 1: wait for the node to go away
    while time.time() < end:
        if find(0x900E) is None:
            break
        time.sleep(0.02)
    # phase 2: wait for it to reappear
    while time.time() < end:
        if find(0x900E) is not None:
            time.sleep(0.05)   # let enumeration settle
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--len", type=int, default=4096)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 64)
    log("#  DDR peek - czy odszyfrowany kod ABL jest w RAM?")
    log("=" * 64)

    probes = [(args.addr, args.len, "custom")] if args.addr else PROBES

    results = []
    for addr, length, label in probes:
        if not wait_fresh_900e(90):
            log("brak swiezej sesji 900E - koncze")
            break
        blob = session(addr, length, label)
        verdict = classify(blob)
        log(f"  -> {len(blob):>6d} B  {verdict}")
        if blob:
            fn = OUT / f"{addr:#012x}_{length}.bin"
            fn.write_bytes(blob)
            log(f"     zapisano {fn.name}")
        results.append((addr, label, len(blob), verdict))
        # let the device drop off and come back for the next probe
        end = time.time() + 40
        while time.time() < end and find(0x900E) is not None:
            time.sleep(0.02)

    log("")
    log("=" * 64)
    log("#  PODSUMOWANIE")
    log("=" * 64)
    for addr, label, n, verdict in results:
        log(f"{addr:#012x}  {n:>6d} B  {label:<28s} {verdict}")

    readable = [r for r in results if r[2] > 0]
    if readable:
        log("")
        log(f">>> DDR ODPOWIADA na {len(readable)} z {len(results)} prob.")
        log(">>> To otwiera analize dzialajacego kodu ABL po odszyfrowaniu.")
    else:
        log("")
        log(">>> DDR nie odpowiada w crashdumpie - potwierdzone malymi blokami.")
        log(">>> Wniosek: handler crashdump nie ma dostepu do DDR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
