#!/usr/bin/env python3
"""Clean Sahara probe: read HELLO, report mode, then RESET properly.

Every earlier script opened a session and abandoned it, leaving the target in
"Sahara error state" - after which it stops cycling and stops answering. That is
almost certainly why the last key-combo test measured a device that was not in a
normal crashdump at all.

This script never leaves a session open:
    HELLO -> report -> SAHARA_RESET (0x07) -> read RESET_RSP -> close

It also reports the *mode*, which is what actually matters:
    mode=2  normal crashdump, usable
    mode=0  genuine EDL (this is what we want to see)
    error   wedged, needs a power cycle
"""
from __future__ import annotations
import struct
import sys
import time
from pathlib import Path

import usb.core

EDL = Path(r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\edl-tools")
sys.path.insert(0, str(EDL))

from edlclient.Library.Connection.usblib import usb_class  # noqa: E402
from edlclient.Library.sahara import sahara  # noqa: E402
from edlclient.Library.sahara_defs import cmd_t  # noqa: E402

T0 = time.time()
MODE_NAMES = {
    0: "IMAGE_TX_PENDING  <- prawdziwy EDL",
    1: "IMAGE_TX_COMPLETE",
    2: "MEMORY_DEBUG      <- crashdump (normalny)",
    3: "COMMAND",
}


def log(m: str) -> None:
    print(f"[{time.time() - T0:7.2f}] {m}", flush=True)


def find():
    return usb.core.find(idVendor=0x05C6, idProduct=0x900E)


def probe_once() -> str:
    cdc = usb_class(portconfig=[[0x05C6, 0x900E, -1]], loglevel=50)
    try:
        if not cdc.connect(EP_IN=-1, EP_OUT=-1):
            return "no-connect"
    except Exception as e:  # noqa: BLE001
        return f"connect-exc:{type(e).__name__}"

    sh = sahara(cdc, loglevel=50)
    result = "unknown"
    try:
        r = sh.connect()
        if not isinstance(r, dict) or r.get("cmd") != cmd_t.SAHARA_HELLO_REQ:
            mode = r.get("mode") if isinstance(r, dict) else None
            if mode == "error":
                log("  HELLO -> ERROR STATE (urządzenie zaklinowane)")
                result = "error"
            else:
                log(f"  HELLO -> {r}")
                result = f"other:{r}"
            r = None

        if r is not None:
            ver = r["data"].version
            mode = r["data"].mode
            log(f"  HELLO ver={ver} mode={mode}  {MODE_NAMES.get(mode, '?')}")
            result = f"mode={mode}"

        # ALWAYS reset, so the next attempt starts clean
        log("  wysylam SAHARA_RESET (0x07)")
        cdc.write(struct.pack("<II", cmd_t.SAHARA_RESET_REQ, 8))
        end = time.time() + 2.0
        while time.time() < end:
            try:
                n = bytes(cdc.usbread(cdc.maxsize, 200))
            except Exception:  # noqa: BLE001
                break
            if not n:
                continue
            cmd = struct.unpack_from("<I", n, 0)[0]
            log(f"  <- cmd 0x{cmd:02x}" +
                ("  RESET_RSP OK" if cmd == cmd_t.SAHARA_RESET_RSP else ""))
            break
    except Exception as e:  # noqa: BLE001
        log(f"  exc {type(e).__name__}: {e}")
        result = f"exc:{type(e).__name__}"
    finally:
        try:
            cdc.close()
        except Exception:  # noqa: BLE001
            pass
    return result


def main() -> int:
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    log("=" * 62)
    log("#  czysta sonda Sahara (zawsze konczy resetem)")
    log("=" * 62)

    end = time.time() + dur
    was = False
    seen = []
    while time.time() < end:
        now = find() is not None
        if now and not was:
            log("--- 900E pojawilo sie, probuje HELLO ---")
            res = probe_once()
            seen.append(res)
        was = now
        time.sleep(0.03)

    log("")
    log("=" * 62)
    log(f"prob: {len(seen)}")
    for s in seen:
        log(f"  {s}")
    if any(s == "mode=0" for s in seen):
        log("")
        log(">>> MODE=0 !!! To jest prawdziwy EDL. Zapis jest mozliwy.")
    elif any(s == "mode=2" for s in seen):
        log("")
        log(">>> Tylko mode=2 (crashdump). Normalny stan tego urzadzenia.")
    elif seen:
        log("")
        log(">>> Urzadzenie nie odpowiada poprawnie - potrzebny power cycle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
