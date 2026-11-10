#!/usr/bin/env python3
"""PMIC PON probe - does the PMIC actually see the Vol- key?

The whole "ROCKNIX ABL cannot reach its menu" theory rests on an untested
assumption: that pressing Volume Down never reaches the hardware. Volume Down
on this board is NOT a TLMM GPIO - it is the PMIC's `pon_resin` input, which
is board-independent on every Qualcomm platform.

This script answers it with a measurement instead of a guess.

Method
------
`PMIC_PON` (0x81b75048) is the PON reason latch. At boot/reset the PMIC records
WHY the device powered up in its low nibble:

    0 PON_KPDPWR        power key only      <- current observed value
    1 PON_RESIN         reset key (= Vol-)  <- what we want to see
    2 PON_KPDPWR_RESIN  both keys
    3 PON_CBLPWR / 6 PON_USB_CHG            <- cable insert

Baseline measured on this tablet: 0x02400200 -> nibble 0 (KPDPWR).

So: hold Volume Down while the device resets. If the nibble becomes 1 or 2,
the PMIC sees the key and the menu route is alive. If it stays 0/3/6 across
several resets with the key held, the key does not reach the PMIC and no button
combination (and no USB stick) can ever work.

Also dumps PMON_HIS (power-on history, PLOG records) for corroboration.

Strictly read-only: Sahara MEMORY_READ only. Nothing is written.

Usage
    python pon_probe.py              # capture every 900E cycle for 120 s
    python pon_probe.py --time 300   # longer
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import usb.core

KIT = Path(__file__).resolve().parent

# edlclient lives in the Linux-port kit, not next to this file
EDL_TOOLS = Path(r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\edl-tools")
if not EDL_TOOLS.is_dir():
    # fallback: search a couple of known locations
    for cand in (KIT / "edl-tools", KIT.parent / "edl-tools",
                 Path(r"C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\edl-tools")):
        if cand.is_dir():
            EDL_TOOLS = cand
            break

sys.path.insert(0, str(KIT))
sys.path.insert(0, str(EDL_TOOLS))

from edlclient.Library.Connection.usblib import usb_class  # noqa: E402
from edlclient.Library.sahara import sahara  # noqa: E402
from edlclient.Library.sahara_defs import cmd_t, sahara_mode_t  # noqa: E402

OUT = KIT / "pon_probe"
T0 = time.time()

PON_REASONS = {
    0: "PON_KPDPWR (power key)",
    1: "PON_RESIN (reset key == Vol-)",
    2: "PON_KPDPWR_RESIN (both keys)",
    3: "PON_CBLPWR (charger insert)",
    4: "PON_RTC (RTC alarm)",
    5: "PON_DC_CHG (DC charger)",
    6: "PON_USB_CHG (USB charger)",
    7: "PON_PON1",
    8: "PON_PON2",
    9: "PON_PON3",
    10: "PON_HARD_RESET",
    11: "PON_SMPL (sample)",
}

# small diagnostic segments; PON is the star, the rest is corroboration
WANT = {
    "PMIC_PON.BIN": "powod wlaczenia (PON latch)",
    "RST_STAT.BIN": "powod resetu",
    "PMON_HIS.BIN": "historia PON",
    "PMPONHIS.BIN": "historia PON (skrot)",
    "FSM_STS.BIN": "reset FSM",
}


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
    out = []
    ENT = 64
    off = 0
    while off + ENT <= len(payload):
        pref, base, length = struct.unpack_from("<QQQ", payload, off)
        desc = payload[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
        fname = payload[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
        if length == 0 or length > (1 << 34):
            break
        out.append({"pref": pref, "addr": base, "len": length,
                    "desc": desc, "file": fname or desc})
        off += ENT
    return out


def mem_read(cdc, addr: int, length: int, desc: str, tmo: float = 4.0) -> bytes:
    pkt = struct.pack("<IIQQ", cmd_t.SAHARA_64BIT_MEMORY_READ,
                      0x08 + 8 + 8, addr, length)
    try:
        if not cdc.write(pkt):
            return b""
    except Exception as err:  # noqa: BLE001
        log(f"    {desc}: write exc {type(err).__name__}")
        return b""
    got = bytearray()
    deadline = time.time() + tmo
    while len(got) < length and time.time() < deadline:
        try:
            n = bytes(cdc.usbread(min(cdc.maxsize, length - len(got)), 300))
        except Exception:  # noqa: BLE001
            break
        if not n:
            continue
        got += n
    return bytes(got)


def decode_pmon_his(blob: bytes) -> None:
    """PMON_HIS is PLOG: 'PLOG' + u32, then records of u8 len + len bytes."""
    idx = blob.find(b"PLOG")
    log(f"    PMON_HIS: {len(blob)} B, PLOG at {idx}")
    if idx < 0:
        return
    off = idx + 8
    n = 0
    while off < len(blob) and n < 40:
        ln = blob[off]
        if ln == 0 or off + 1 + ln > len(blob):
            break
        rec = blob[off + 1:off + 1 + ln]
        log(f"      rec[{n}] len={ln:3d}  {rec.hex(' ')}")
        off += 1 + ln
        n += 1


def one_session(outdir: Path, seq: int) -> dict | None:
    """Catch one 900E session, read the diagnostics, return decoded values."""
    cdc, sh = connect(0x900E)
    if not cdc:
        return None

    res: dict = {"seq": seq}
    try:
        r = sh.connect()
        if not isinstance(r, dict) or r.get("cmd") != cmd_t.SAHARA_HELLO_REQ:
            return None
        ver = r["data"].version
        mode = r["data"].mode
        if mode != 2:
            log(f"  (mode={mode}, nie crashdump - pomijam)")
            return None

        cdc.write(struct.pack("<IIIIIIIIIIII", cmd_t.SAHARA_HELLO_RSP, 0x30,
                              ver, 1, 0, sahara_mode_t.SAHARA_MODE_MEMORY_DEBUG,
                              1, 2, 3, 4, 5, 6))
        r = sh.get_rsp()
        if not isinstance(r, dict) or r.get("cmd") not in (
                cmd_t.SAHARA_MEMORY_DEBUG, cmd_t.SAHARA_64BIT_MEMORY_DEBUG):
            return None

        pkt = r["data"]
        table = mem_read(cdc, pkt.memory_table_addr, pkt.memory_table_length,
                         "TABLE", tmo=3.0)
        if not table:
            return None
        entries = parse_table(table)
        wanted = [e for e in entries if e["file"] in WANT]

        for e in wanted:
            blob = mem_read(cdc, e["addr"], e["len"], e["file"])
            if not blob:
                log(f"  -- {e['file']:14s} pusty")
                continue
            (outdir / f"{seq:02d}_{e['file']}").write_bytes(blob)
            res[e["file"]] = blob

        if "PMIC_PON.BIN" in res and len(res["PMIC_PON.BIN"]) >= 8:
            v = struct.unpack_from("<Q", res["PMIC_PON.BIN"], 0)[0]
            nib = v & 0xF
            res["pon_raw"] = v
            res["pon_nibble"] = nib
            log(f"  PMIC_PON = 0x{v:016x}  nibble={nib} -> "
                f"{PON_REASONS.get(nib, 'nieznany')}")
        if "RST_STAT.BIN" in res and len(res["RST_STAT.BIN"]) >= 4:
            v = struct.unpack_from("<I", res["RST_STAT.BIN"], 0)[0]
            bits = [f"b{i}" for i in range(32) if v & (1 << i)]
            res["rst_stat"] = v
            log(f"  RST_STAT = 0x{v:08x}  bity: {', '.join(bits) or 'brak'}")
        if "PMON_HIS.BIN" in res:
            decode_pmon_his(res["PMON_HIS.BIN"])
        return res
    except Exception as err:  # noqa: BLE001
        log(f"  session exc {type(err).__name__}: {err}")
        return None
    finally:
        try:
            cdc.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=120.0, help="how long to watch")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    log("=" * 62)
    log("#  PMIC PON probe - czy PMIC widzi klawisz Vol- ?")
    log("=" * 62)
    log("")
    log("INSTRUKCJA: TRZYMAJ Volume Down (sciszanie) przez CALY czas.")
    log("Tablet sam sie resetuje - kazdy nowy cykl to nowy zatrzask PON.")
    log("")

    sessions = []
    seq = 0
    deadline = time.time() + args.time
    was_present = False

    while time.time() < deadline:
        present = find(0x900E) is not None
        if present and not was_present:
            seq += 1
            log(f"--- sesja #{seq}: 900E pojawilo sie ---")
            r = one_session(OUT, seq)
            if r:
                sessions.append(r)
            was_present = True
        elif not present:
            was_present = False
        time.sleep(0.05)

    log("")
    log("=" * 62)
    log("#  WYNIK")
    log("=" * 62)
    if not sessions:
        log("brak udanych sesji - sprawdz kabel/driver/stan tabletu")
        return 1

    log(f"sesji: {len(sessions)}")
    log("")
    log(f"{'#':>3}  {'PMIC_PON':>18}  {'nib':>3}  powod")
    log("-" * 62)
    nibbles = []
    for s in sessions:
        if "pon_raw" in s:
            nib = s["pon_nibble"]
            nibbles.append(nib)
            log(f"{s['seq']:>3}  {s['pon_raw']:#018x}  {nib:>3}  "
                f"{PON_REASONS.get(nib, 'nieznany')}")
        else:
            log(f"{s['seq']:>3}  {'-':>18}  {'-':>3}  brak odczytu")

    log("")
    if not nibbles:
        log("Nie udalo sie odczytac PMIC_PON w zadnej sesji.")
        return 1

    resin = [n for n in nibbles if n in (1, 2)]
    if resin:
        log(">>> WYNIK: PMIC WIDZI klawisz. Powod wlaczenia zawiera RESIN.")
        log(">>> Droga przez menu ROCKNIX ABL jest OTWARTA - klawisz dociera")
        log(">>> do sprzetu, wiec problemem jest timing/tryb, nie pin.")
        verdict = "RESIN"
    elif all(n == nibbles[0] for n in nibbles):
        log(f">>> WYNIK: we wszystkich {len(nibbles)} sesjach ten sam powod "
            f"({PON_REASONS.get(nibbles[0], nibbles[0])}).")
        log(">>> Klawisz NIE zmienil zatrzasku PON.")
        log(">>> Uwaga: zatrzask dotyczy momentu WLACZENIA. Jesli reset")
        log(">>> pochodzi z watchdoga (a nie z PON), RESIN nie musi sie")
        log(">>> zapisac - sprawdz PMON_HIS powyzej przed wyciagnieciem wniosku.")
        verdict = "BRAK"
    else:
        log(">>> WYNIK: zatrzask ZMIENIAL sie miedzy sesjami - klawisz ma")
        log(">>> wplyw na PMIC. Patrz tabela powyzej.")
        verdict = "ZMIENNY"

    log("")
    log(f"pliki w: {OUT}")
    log(f"werdykt: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
