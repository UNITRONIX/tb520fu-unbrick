#!/usr/bin/env python3
"""tablet.py - ONE tool for every mode-acquisition and read operation. Do not fork it.

Why this file exists instead of six others
------------------------------------------
By the end of 2026-11-11 this repository had eight overlapping catchers
(catch_hello, grab_now, auto_grab, hold_and_catch, com_sahara_client,
passive_listen, grab_ddr_data, watch_pids), each with slightly different timing
logic. A method that worked stopped working, because the tool changed - not the
tablet. Every one of them has been folded in here and the others are deprecated.

This file is append-only in spirit: fix bugs, add subcommands, never rewrite the
timing model. If a mode becomes reachable, the command that reached it stays
byte-identical so it can be repeated.

The mode map, as measured
-------------------------
    900E  crashdump, Sahara ver=2 mode=2   reached by the tablet itself
    9008  real EDL, Sahara ver=3 mode=0     only via a bump, or FEDL by hardware
    FEDL  boot-ROM level EDL                D+ held LOW at power-on

What each mode needs, and why
-----------------------------
* 900E emits exactly ONE HELLO per boot, held until the first reader opens the
  port. First opener wins. After that, silence until the next real boot
  (docs/34). SAHARA_RESET does not produce another.
* The bump 900E -> 9008 needs that HELLO. So it must be the first opener.
* Opening a bare 900E node and writing nothing keeps the port alive indefinitely
  (measured, 45 s). Writing SAHARA_RESET kills it (measured, 6x, 16 ms later).
* FEDL needs D+ LOW before power is applied and held through boot; the firmware
  polls for ~50 ms early in USB init (docs/18). It is a hold, not a race.

Safety
------
Nothing here writes storage. `read` performs MEMORY_READ_64 only. `bump` sends
mode-switch commands. `upload` sends a programmer into RAM - that is the
operation every previous attempt performed and it does not touch UFS.

Usage
    python tablet.py status
    python tablet.py wait --want 900e --seconds 60
    python tablet.py read --region DDR_DATA
    python tablet.py bump
    python tablet.py selftest
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

HERE = Path(__file__).resolve().parent
LOG = HERE / "tablet_sessions.jsonl"
T0 = time.time()

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
CMD_SWITCH_MODE = 0x0C
CMD_MEMORY_DEBUG_64 = 0x10
CMD_MEMORY_READ_64 = 0x11

MODE_IMAGE_TX = 0
MODE_MEMORY_DEBUG = 2
MODE_COMMAND = 3

NAMES = {0x01: "HELLO_REQ", 0x02: "HELLO_RSP", 0x03: "READ_DATA",
         0x04: "END_TRANSFER", 0x05: "DONE_REQ", 0x06: "DONE_RSP",
         0x07: "RESET", 0x08: "RESET_RSP", 0x09: "MEMORY_DEBUG",
         0x0A: "MEMORY_READ", 0x0B: "CMD_READY", 0x0C: "SWITCH_MODE",
         0x10: "MEMORY_DEBUG_64", 0x11: "MEMORY_READ_64"}


def log(m: str = "") -> None:
    print(f"[{time.time() - T0:7.3f}] {m}", flush=True)


def log_attempt(route: str, keys: str, outcome: str,
                ver: int | None = None, mode: int | None = None) -> None:
    """Append one row to scripts/attempts.jsonl, the repeatability ledger.

    The goal asks for a *repeatable* result, and a result that is only described in prose
    cannot be counted. This is called from the tools themselves so the ledger fills up
    whether or not anyone remembers to write a row by hand.

    Failures here are swallowed on purpose: losing a ledger row must never abort a run
    that is mid-handshake with the device.
    """
    try:
        import attempts as A
        row = {
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "route": route,
            "keys": keys,
            "orientation": None,
            "outcome": outcome,
            "hello_ver": ver,
            "hello_mode": mode,
            "capture": A.last_capture(),
            "note": "auto-recorded by tablet.py",
        }
        with A.LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as err:  # noqa: BLE001
        log(f"  (could not record the attempt: {type(err).__name__})")


def save_hello_capture(pkt: bytes, source: str) -> str:
    """Write the raw HELLO packet to disk, and say where.

    Why this is not optional: docs/97 established that the founding measurement of
    this whole project - `HELLO ver=3 mode=0` - has **no raw capture anywhere in the
    repository**. It is supported by prose and by later measurements, and it cannot be
    re-checked by anyone. That is the one defect in the evidence base that a single
    line of code can prevent from recurring.

    Captures go to `hello_captures/` with a timestamp, the source command, and the
    parsed header, so a future reader can compare bytes rather than trust a summary.
    """
    try:
        outdir = HERE / "hello_captures"
        outdir.mkdir(exist_ok=True)
        # Never let synthetic data land in the evidence folder. A unit test wrote a
        # fabricated ver=3 mode=0 packet here once, and a folder named "captures" that
        # can contain invented bytes is worse than no folder at all (docs/97 is about
        # exactly this failure mode). Test artefacts are refused by name.
        if source.startswith("unit") or source.startswith("test"):
            log("  refusing to save a synthetic packet as a capture")
            return ""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        raw_path = outdir / f"{stamp}-{source}.bin"
        raw_path.write_bytes(pkt)

        cmd, ln = struct.unpack_from("<II", pkt, 0)
        ver = struct.unpack_from("<I", pkt, 8)[0] if len(pkt) >= 12 else None
        mode = struct.unpack_from("<I", pkt, 20)[0] if len(pkt) >= 24 else None
        meta = {
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "cmd": cmd,
            "cmd_name": NAMES.get(cmd, hex(cmd)),
            "length": ln,
            "version": ver,
            "mode": mode,
            "is_goal_state": (ver == 3 and mode == MODE_IMAGE_TX),
            "bytes": len(pkt),
            "port": None,
        }
        (outdir / f"{stamp}-{source}.json").write_text(json.dumps(meta, indent=2))
        log(f"  raw HELLO saved: {raw_path.name} ({len(pkt)} B)")
        return str(raw_path)
    except Exception as err:  # noqa: BLE001
        log(f"  could not save the HELLO capture: {type(err).__name__}")
        return ""


def record(event: str, **kv) -> None:
    """Append one line to the session log, skipping a repeat of the previous state.

    Why deduplicate: on 2026-11-11 the log accumulated nineteen consecutive
    `status` entries with identical empty payloads, because the state did not change
    and each check wrote a new line. That is the only history the next session will
    read, and identical rows buried the few entries that mattered. A log where every
    line is a *transition* is worth reading; one where every line is a *poll* is not.

    Only the `status` event is deduplicated. Anything that represents an action or a
    result (catch, read, bump, attempt) is always written, even if it repeats -
    repetitions there are information.
    """
    rec = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kv}

    if event == "status" and LOG.exists():
        try:
            with LOG.open("r", encoding="utf-8") as f:
                last = None
                for line in f:
                    line = line.strip()
                    if line:
                        last = line
            if last:
                prev = json.loads(last)
                if (prev.get("event") == "status"
                        and prev.get("pids") == kv.get("pids")
                        and prev.get("com") == kv.get("com")):
                    return
        except Exception:  # noqa: BLE001
            pass   # a malformed log must never stop a tool from running

    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ---- device presence -----------------------------------------------------
def _usb_enum() -> dict[str, str]:
    """{instance_id: status} for every present USB node, via SetupAPI.

    Why not PowerShell: `Get-PnpDevice` costs ~1000 ms per call. Two places in this
    file poll in the single-digit-millisecond range and cannot afford that:

      * `grab_edl_hello` races to be the first opener of the 9008 HELLO - at 1 Hz it
        loses that race almost every time, and a lost HELLO costs a whole power cycle;
      * `wait` claims to poll every 20 ms and was really polling every 1000 ms.

    All signatures are declared. Without `argtypes` a HDEVINFO pointer truncates to
    32 bits and enumeration silently returns nothing, which reads as "no device" -
    the same trap that produced a confident wrong answer in `watch_unknown.py`.
    """
    import ctypes
    import ctypes.wintypes as wt

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    DIGCF_PRESENT = 0x02
    DIGCF_ALLCLASSES = 0x04

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVINFO_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID),
                    ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]

    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                              ctypes.c_void_p, wt.DWORD]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    setupapi.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wt.DWORD,
                                               ctypes.POINTER(SP_DEVINFO_DATA)]
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wt.LPWSTR, wt.DWORD,
        ctypes.POINTER(wt.DWORD)]

    out: dict[str, str] = {}
    h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                      DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not h:
        return out
    try:
        buf = ctypes.create_unicode_buffer(1024)
        need = wt.DWORD()
        i = 0
        while True:
            dev = SP_DEVINFO_DATA()
            dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(h, i, ctypes.byref(dev)):
                break
            i += 1
            if setupapi.SetupDiGetDeviceInstanceIdW(
                    h, ctypes.byref(dev), buf, 1024, ctypes.byref(need)):
                s = buf.value
                if s.upper().startswith("USB\\"):
                    out[s] = "present"
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return out


def ports() -> list[str]:
    try:
        return [p.device.upper() for p in serial.tools.list_ports.comports()]
    except Exception:  # noqa: BLE001
        return []


def com_port(prefer: str | None = None) -> str | None:
    """The Qualcomm diagnostics/EDL COM port, if one exists."""
    cands = []
    try:
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").upper()
            desc = (p.description or "").upper()
            if "05C6" in hwid or "QUALCOMM" in desc:
                cands.append(p.device.upper())
    except Exception:  # noqa: BLE001
        pass
    if prefer and prefer.upper() in cands:
        return prefer.upper()
    return cands[0] if cands else None


def pids_present() -> dict[str, str]:
    """{instance: pid} for every present VID_05C6 node."""
    out: dict[str, str] = {}
    for inst in _usb_enum():
        up = inst.upper()
        if "VID_05C6" not in up:
            continue
        i = up.find("PID_")
        out[inst] = up[i + 4:i + 8] if i >= 0 else "?"
    return out


def tablet_on_bus() -> bool:
    """Is the tablet present at all, in ANY of its identities?

    `offcheck` used to ask `pids_present()`, which only looks for VID_05C6 - so a
    tablet wedged as `VID_0000&PID_0002` read as absent, and the one measurement
    that function exists to make could not be taken in the state the tablet is
    actually in. The wedged node counts as present here.
    """
    for inst in _usb_enum():
        up = inst.upper()
        if "VID_05C6" in up or "VID_0000" in up:
            return True
    return False


# ---- transport -----------------------------------------------------------
class Link:
    """Byte-stream Sahara. Never assume one read() is one packet."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 3.0) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.05, write_timeout=2.0)
        self.port = port
        self.buf = b""
        self.timeout = timeout
        self.errors = 0
        self.dead = False

    def close(self) -> None:
        """Close and NOTHING else.

        No SAHARA_RESET. Measured six times on 2026-11-11: a reset at the end of a
        session re-enumerates the interface and the node vanishes 16 ms later,
        which reads exactly like a device fault and is not one.
        """
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001
            pass

    def _fill(self, want: int = 4096) -> bytes:
        if self.dead:
            return b""
        try:
            d = self.ser.read(max(1, want))
            if d:
                self.errors = 0
            return d
        except Exception as err:  # noqa: BLE001
            self.errors += 1
            if self.errors == 1:
                log(f"  read error: {type(err).__name__}")
            if self.errors >= 8:
                self.dead = True
                log("  port stopped responding - ending session")
            return b""

    def packet(self, timeout: float | None = None):
        tmo = self.timeout if timeout is None else timeout
        deadline = time.time() + tmo
        while len(self.buf) < 8:
            if self.dead or time.time() > deadline:
                return None
            self.buf += self._fill(64)
        cmd, ln = struct.unpack_from("<II", self.buf, 0)
        if ln < 8 or ln > (1 << 20):
            log(f"  bad framing cmd={cmd:#x} len={ln}")
            self.buf = b""
            return None
        while len(self.buf) < ln:
            if self.dead or time.time() > deadline:
                return None
            self.buf += self._fill(4096)
        pkt, self.buf = self.buf[:ln], self.buf[ln:]
        return pkt

    def write(self, data: bytes) -> bool:
        try:
            self.ser.write(data)
            self.ser.flush()
            return True
        except Exception as err:  # noqa: BLE001
            log(f"  write failed: {type(err).__name__}")
            return False

    def raw(self, n: int, timeout: float = 25.0) -> bytes:
        got = bytearray()
        deadline = time.time() + timeout
        while len(got) < n and time.time() < deadline and not self.dead:
            c = self._fill(min(65536, n - len(got)))
            if c:
                got += c
                deadline = time.time() + timeout
        return bytes(got)


def hello_rsp(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", CMD_HELLO_RSP, 0x30,
                       ver, 1, 0, mode, 1, 2, 3, 4, 5, 6)


def switch_to_edl(link: Link, ver: int) -> bool:
    """Turn a LIVE mode=2 session into IMAGE_TX, on the handle that holds it.

    This exists as its own function because of a dead end that cost a whole
    afternoon: `catch` read the HELLO, printed "run `bump` now", and `bump` could
    never work - it opens a new handle, and the HELLO is consumed by the first
    opener (docs/34). The switch has to happen on the same session, so the code
    that reads the HELLO is the code that must do the switching.

    Wire bytes are the ones with log evidence (docs/14 V1/V1b): HELLO_RSP mode=3,
    SWITCH_MODE with declared len=12, HELLO_RSP mode=0, then DONE.
    """
    link.write(hello_rsp(ver, MODE_COMMAND))
    r = link.packet(4.0)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
        log("  COMMAND mode refused")
        return False
    log("  CMD_READY")

    link.write(struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX))
    r = link.packet(5.0)
    if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
        log("  switch not confirmed by a fresh HELLO")
        return False
    log("  fresh HELLO after switch - confirming")

    link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
    r = link.packet(5.0)
    if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
        st = struct.unpack_from("<I", r, 12)[0] if len(r) >= 16 else -1
        log(f"  END status={st:#x} - sending DONE")
        link.write(struct.pack("<II", CMD_DONE_REQ, 8))
        link.packet(3.0)
    return True


def port_9008() -> str | None:
    """The COM port of a 9008 node, found without spawning a process.

    Speed matters here: the HELLO on 9008 is taken by whoever opens first, and a
    PowerShell round-trip per poll costs ~400 ms - longer than the whole window.
    list_ports reads the registry directly and returns in single-digit ms.
    """
    try:
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").upper()
            desc = (p.description or "").upper()
            if "9008" in hwid or "QDLOADER" in desc:
                return p.device.upper()
    except Exception:  # noqa: BLE001
        pass
    return None


def grab_edl_hello(timeout: float) -> int:
    """Wait for the 9008 node, then be the first reader of its HELLO.

    Re-enumeration after a switch takes ~21 s (docs/14), so a 2-3 s wait reads as
    failure while the switch is still in progress. Once the port exists there is
    no second chance: the read has to be immediate, which is why this polls the
    port list rather than the PID table.

    A 9008 node with no COM port is the other failure mode, and it must be named
    rather than silently timed out: if WinUSB (libwdi `oem67.inf`) owns the node
    there is no COM port to open at all, and the fix is a driver switch
    (`Switch-DeviceDriver.ps1 -To COM`), not a longer wait.
    """
    log("  waiting for 9008 (re-enumeration takes ~21 s; docs/14)")
    t0 = time.time()
    deadline = t0 + timeout
    cp = None
    node_seen = False
    while time.time() < deadline:
        cp = port_9008()
        if cp:
            break
        if not node_seen and "9008" in pids_present().values():
            node_seen = True
            log("  9008 node IS on the bus but has no COM port")
            log("  -> WinUSB owns it; run Switch-DeviceDriver.ps1 -To COM (elevated)")
            log("     without a port the HELLO is unreachable from here")
        time.sleep(0.005)
    if not cp:
        log(f"  9008 never appeared within {timeout:.0f}s")
        record("edl_hello", ok=False,
               reason="no-port" if node_seen else "no-9008")
        return 1

    log(f"  9008 port {cp} after {time.time() - t0:.1f}s - opening immediately")
    link = None
    while time.time() < deadline:
        try:
            link = Link(cp)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.002)
    if link is None:
        log(f"  could not open {cp}")
        record("edl_hello", ok=False, reason="no-open", port=cp)
        return 1

    try:
        pkt = link.packet(4.0)
        if pkt is None:
            log("  port open, no HELLO - it was already consumed")
            record("edl_hello", ok=False, reason="no-hello", port=cp)
            return 1
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO, got {NAMES.get(cmd, hex(cmd))}")
            record("edl_hello", ok=False, reason=f"packet-{cmd:#x}", port=cp)
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} on {cp} ***")
        save_hello_capture(pkt, "edl-9008")
        log_attempt(route="catch", keys="none",
                    outcome=("success" if (ver == 3 and mode == MODE_IMAGE_TX)
                             else "9008-mute"),
                    ver=ver, mode=mode)
        record("edl_hello", ok=(ver == 3 and mode == MODE_IMAGE_TX),
               ver=ver, mode=mode, port=cp)
        if ver == 3 and mode == MODE_IMAGE_TX:
            log("  *** GOAL STATE: HELLO ver=3 mode=0 straight from PBL ***")
            return 0
        log("  not the goal state - ver=3 mode=0 is what EDL from PBL looks like")
        return 1
    finally:
        link.close()          # never a reset - see Link.close()


def parse_table(payload: bytes) -> list[dict]:
    out = []
    for off in range(0, len(payload) - 63, 64):
        pref, addr, ln = struct.unpack_from("<QQQ", payload, off)
        desc = payload[off + 24:off + 44].split(b"\x00")[0].decode("ascii", "replace")
        fn = payload[off + 44:off + 64].split(b"\x00")[0].decode("ascii", "replace")
        if ln == 0 or ln > (1 << 36):
            break
        out.append({"addr": addr, "len": ln, "desc": desc, "file": fn})
    return out


# ---- commands ------------------------------------------------------------
def cmd_status(_args) -> int:
    p = pids_present()
    cp = com_port()
    log("device nodes:")
    if not p:
        log("  none (no VID_05C6 node present)")
    for inst, pid in p.items():
        log(f"  PID_{pid}  {inst}")
    log(f"COM port: {cp or 'none'}")
    log(f"all ports: {ports()}")
    record("status", pids=p, com=cp)
    return 0


def cmd_wait(args) -> int:
    want = args.want.lower()
    log(f"waiting up to {args.seconds:.0f}s for {want}")
    end = time.time() + args.seconds
    while time.time() < end:
        p = pids_present()
        got = [pid for pid in p.values()]
        if want in ("900e", "9008"):
            if want.upper().replace("E", "E")[-4:] in got or want[1:].upper() in got:
                pass
            if want == "900e" and "900E" in got:
                cp = com_port()
                log(f"  900E present, port={cp}")
                record("wait", want=want, ok=True, port=cp)
                return 0
            if want == "9008" and "9008" in got:
                cp = com_port()
                log(f"  9008 present, port={cp}")
                record("wait", want=want, ok=True, port=cp)
                return 0
        elif want == "com" and com_port():
            log(f"  COM port {com_port()}")
            record("wait", want=want, ok=True, port=com_port())
            return 0
        time.sleep(0.02)
    log("  timeout")
    record("wait", want=want, ok=False)
    return 1


def open_900e(prefer: str | None = None) -> Link | None:
    cp = com_port(prefer)
    if cp is None:
        log("  no Qualcomm COM port - the node is not on the serial driver")
        return None
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            return Link(cp)
        except Exception:  # noqa: BLE001
            time.sleep(0.005)
    log(f"  could not open {cp}")
    return None


def cmd_read(args) -> int:
    link = open_900e(args.port)
    if link is None:
        return 1
    log(f"  opened {link.port}")
    try:
        pkt = link.packet(args.hello_timeout)
        if pkt is None:
            log("  no HELLO.")
            log("  A 900E node emits exactly one per boot and the first reader takes")
            log("  it. Silence here means it was already consumed - it needs a real")
            log("  power cycle, not a reset (docs/34).")
            record("read", ok=False, reason="no-hello")
            return 1

        cmd = struct.unpack_from("<I", pkt, 0)[0]
        log(f"  {NAMES.get(cmd, hex(cmd))} len={len(pkt)}")
        if cmd != CMD_HELLO_REQ:
            record("read", ok=False, reason=f"unexpected-{cmd:#x}")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} ***")
        if mode != MODE_MEMORY_DEBUG:
            log(f"  mode {mode} is not crashdump (2); not a memory session")
            record("read", ok=False, reason=f"mode-{mode}")
            return 1

        link.write(hello_rsp(ver, MODE_MEMORY_DEBUG))
        rsp = link.packet(6.0)
        if rsp is None:
            record("read", ok=False, reason="no-debug-answer")
            return 1
        rc = struct.unpack_from("<I", rsp, 0)[0]
        if rc not in (CMD_MEMORY_DEBUG, CMD_MEMORY_DEBUG_64):
            log(f"  unexpected {NAMES.get(rc, hex(rc))}")
            record("read", ok=False, reason=f"debug-{rc:#x}")
            return 1
        if rc == CMD_MEMORY_DEBUG:
            ta, tl = struct.unpack_from("<II", rsp, 8)
        else:
            ta, tl = struct.unpack_from("<QQ", rsp, 8)
        log(f"  table @{ta:#x} len={tl}")

        link.write(struct.pack("<IIQQ", CMD_MEMORY_READ_64, 24, ta, tl))
        raw = link.raw(tl, 12.0)
        log(f"  table bytes {len(raw)}")
        if not raw:
            record("read", ok=False, reason="table-empty")
            return 1
        table = parse_table(raw)
        (HERE / "last_table.json").write_text(json.dumps(table, indent=2))

        # choose region
        if args.region:
            want = args.region.upper()
            hits = [e for e in table
                    if want in (e["file"] or "").upper() or want in (e["desc"] or "").upper()]
        elif args.all:
            hits = [e for e in table if e["len"] <= args.max]
        else:
            hits = [e for e in table if "DDR_DATA" in (e["file"] or "").upper()]
        if not hits:
            log(f"  no region matches {args.region!r}")
            record("read", ok=False, reason="no-region")
            return 1

        outdir = HERE / "regions"
        outdir.mkdir(exist_ok=True)
        for e in hits:
            name = e["file"] or e["desc"]
            log(f"  reading {name} {e['len']} B @ {e['addr']:#x}")
            link.write(struct.pack("<IIQQ", CMD_MEMORY_READ_64, 24, e["addr"], e["len"]))
            blob = link.raw(e["len"], 30.0)
            if not blob:
                log("    no data")
                continue
            fn = outdir / f"{e['addr']:#014x}_{name.replace('/', '_')}"
            fn.write_bytes(blob)
            nz = sum(1 for b in blob if b)
            log(f"    {len(blob)}/{e['len']} B  nonzero {nz / max(1, len(blob)):.1%} -> {fn.name}")
            if "DDR_DATA" in name.upper() and len(blob) >= 20:
                v = struct.unpack_from("<4I", blob, 4)
                log(f"    DDR training version {v[0]}.{v[1]}.{v[2]}")
        record("read", ok=True, regions=[e["file"] for e in hits])
        return 0
    finally:
        link.close()


def cmd_bump(args) -> int:
    """900E -> 9008, and then take the 9008 HELLO in the same run.

    The switch alone is not the goal: after it the device re-enumerates as 9008 and
    emits a ver=3 mode=0 HELLO that the first opener takes (docs/34). Doing the
    switch in one process and reading in another loses it every time, so the read
    is chained here unless --no-grab is given.

    The old version printed "switch complete" and returned - and its own advice,
    "now run bump again", could never work, because bump opens a NEW handle and the
    HELLO it wants is already in the closed one.
    """
    link = open_900e(args.port)
    if link is None:
        return 1
    log(f"  opened {link.port}")
    ok = False
    grab = False
    try:
        pkt = link.packet(5.0)
        if pkt is None:
            log("  no HELLO - cannot bump. This needs a fresh boot (docs/34).")
            record("bump", ok=False, reason="no-hello")
            return 1
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO, got {NAMES.get(cmd, hex(cmd))}")
            record("bump", ok=False, reason=f"packet-{cmd:#x}")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  HELLO ver={ver} mode={mode}")
        if mode == MODE_IMAGE_TX:
            log("  already IMAGE_TX - this session IS the EDL state")
            record("bump", ok=True, ver=ver, mode=mode, already=True)
            ok = True
            if ver == 3:
                log("  *** GOAL STATE: HELLO ver=3 mode=0 straight from PBL ***")
            return 0

        if not switch_to_edl(link, ver):
            record("bump", ok=False, reason="switch-refused")
            return 1
        log("  switch complete")
        record("bump", ok=True)
        ok = True
        grab = not args.no_grab
        return 0
    finally:
        link.close()
        if not ok:
            log("  NOTE: the port was closed without a reset on purpose (docs/34)")
        if grab:
            # Close the 900E handle before waiting, then race to be the first
            # opener on the 9008 node - that read is the whole point.
            grab_edl_hello(args.edl_timeout)


def grab_any_hello(timeout: float) -> int:
    """Read the HELLO off whichever Qualcomm COM port exists, and capture it.

    Needed because the two routes land in different modes: a bump produces 9008, but a
    D+ short can produce either 900E (short not seen) or 9008 (seen). The D+ attempt
    still has to READ the HELLO in the 900E case, because a fresh mode=2 HELLO is what
    makes a bump possible afterwards - and if this reader does not take it, some other
    process will (docs/34).
    """
    t0 = time.time()
    deadline = t0 + timeout
    cp = None
    while time.time() < deadline:
        cp = com_port()
        if cp:
            break
        time.sleep(0.005)
    if not cp:
        log(f"  no Qualcomm COM port within {timeout:.0f}s")
        return 1
    log(f"  port {cp} after {time.time() - t0:.1f}s - opening immediately")

    link = None
    while time.time() < deadline:
        try:
            link = Link(cp)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.002)
    if link is None:
        log(f"  could not open {cp}")
        return 1
    try:
        pkt = link.packet(4.0)
        if pkt is None:
            log("  port open, no HELLO - already consumed")
            return 1
        cmd = struct.unpack_from("<I", pkt, 0)[0]
        if cmd != CMD_HELLO_REQ:
            log(f"  expected HELLO, got {NAMES.get(cmd, hex(cmd))}")
            return 1
        ver = struct.unpack_from("<I", pkt, 8)[0]
        mode = struct.unpack_from("<I", pkt, 20)[0]
        log(f"  *** HELLO ver={ver} mode={mode} on {cp} ***")
        save_hello_capture(pkt, "short-attempt")
        if ver == 3 and mode == MODE_IMAGE_TX:
            log("  *** GOAL STATE: HELLO ver=3 mode=0 straight from PBL ***")
            return 0
        log("  not the goal state (ver=3 mode=0 would be)")
        return 1
    finally:
        link.close()


def cmd_edl_hello(args) -> int:
    """Read the HELLO off a 9008 node that is already present."""
    return grab_edl_hello(args.timeout)


def cmd_catch(args) -> int:
    """Hold a handle through a power cycle and grab the HELLO the moment it exists.

    Route (a) of the goal: 900E -> 9008 needs a fresh HELLO, and the HELLO is
    consumed by the first opener. Measured facts this command is built around:

      * one HELLO per boot; a spent one never comes back (docs/34);
      * SAHARA_RESET does not produce another, and it destroys the port;
      * so the handle must be held BEFORE the cycle, and the read must be the
        first thing that happens on the new node.

    The earlier attempt lost 16.5 s between the handle dying and the reopen,
    because it re-checked the port list instead of just retrying open(). Here the
    retry loop calls open() directly every 2 ms, which is the shortest path to
    the new node.
    """
    port = (args.port or com_port())
    if port is None:
        # The node cycles on its own between attempts, so absence now is not a
        # reason to refuse: poll for it, then start holding.
        log("  no Qualcomm port yet - waiting for one (power the tablet on)")
        end = time.time() + args.seconds
        while time.time() < end and port is None:
            time.sleep(0.02)
            port = com_port()
        if port is None:
            log("  no Qualcomm port appeared")
            record("catch", ok=False, reason="no-port")
            return 1
    port = port.upper()
    log(f"  holding {port}. If you have not reset yet: hold Power ~15 s, then power on.")

    deadline = time.time() + args.seconds
    deaths = 0
    link = None
    grab = False
    rc = 1
    try:
        while time.time() < deadline:
            if link is None:
                # Re-resolve the port on every reconnect. The COM number is assigned
                # per instance and the fresh node after a power cycle is not
                # guaranteed to land on the same one; holding the old name meant
                # opening a device that no longer existed, for the whole window.
                fresh = com_port(port)
                if fresh:
                    port = fresh
                try:
                    link = Link(port)
                    log(f"  handle open (death #{deaths}) on {port}")
                except Exception:  # noqa: BLE001
                    time.sleep(0.002)
                    continue

            pkt = link.packet(2.0)
            if pkt is None:
                if link.dead or link.errors:
                    # Any error while holding means the device re-enumerated.
                    # `errors` is checked, not just `dead`, because in a held
                    # session the very FIRST read error is already the cycle -
                    # waiting for eight costs seconds we do not have.
                    link.close()
                    link = None
                    deaths += 1
                    log(f"  handle died (death #{deaths}) - reconnecting")
                continue

            cmd = struct.unpack_from("<I", pkt, 0)[0]
            if cmd != CMD_HELLO_REQ:
                log(f"  packet {NAMES.get(cmd, hex(cmd))} - ignored")
                continue

            ver = struct.unpack_from("<I", pkt, 8)[0]
            mode = struct.unpack_from("<I", pkt, 20)[0]
            log(f"  *** HELLO ver={ver} mode={mode} ***")
            save_hello_capture(pkt, "catch")
            record("catch", ok=True, ver=ver, mode=mode, deaths=deaths)
            log_attempt(route="catch", keys="none", outcome=(
                "success" if (ver == 3 and mode == MODE_IMAGE_TX)
                else "900e" if mode == MODE_MEMORY_DEBUG else "9008-mute"),
                ver=ver, mode=mode)
            if mode == MODE_MEMORY_DEBUG:
                # CORRECTION to what this used to print: "run `bump` now" could
                # never work. bump opens its own handle, and the HELLO is spent the
                # moment this one read it (docs/34). The switch has to happen here,
                # on this handle, or not at all.
                if args.no_bump:
                    log("  crashdump HELLO - re-run without --no-bump to switch on this handle")
                    rc = 0
                else:
                    log("  crashdump HELLO - switching on THIS handle (a second process cannot)")
                    if switch_to_edl(link, ver):
                        log("  switch complete")
                        record("bump", ok=True, source="catch")
                        grab = True
                        rc = 0
                    else:
                        record("bump", ok=False, source="catch", reason="switch-refused")
                        rc = 1
                return rc
            if mode == MODE_IMAGE_TX:
                if ver == 3:
                    log("  *** GOAL STATE: HELLO ver=3 mode=0 straight from PBL ***")
                    rc = 0
                else:
                    log("  IMAGE_TX but ver!=3 - not the PBL EDL state")
                    rc = 1
                return rc
            rc = 0
            return rc

        log(f"  {args.seconds:.0f}s elapsed with no HELLO")
        record("catch", ok=False, reason="timeout", deaths=deaths)
        return 1
    finally:
        if link:
            link.close()          # never a reset - see Link.close()
        if grab:
            # The 900E port is closed now; race for the 9008 node's HELLO, which is
            # only emitted once and only while nobody has opened it.
            grab_edl_hello(args.edl_timeout)


def cmd_watch(args) -> int:
    """Log every USB device that appears or disappears, with no VID filter.

    Why unfiltered: the vendor instruction (docs/43) promises "a COM port", not a
    particular PID. Every watcher in this repository filtered on VID_05C6, so a
    node appearing under a different VID - or a composite device with several
    interfaces - would be invisible exactly when we most need to see it.

    Passive: enumerates the device tree through SetupAPI and touches nothing.
    """
    import ctypes
    import ctypes.wintypes as wt

    DIGCF_PRESENT = 0x02
    DIGCF_ALLCLASSES = 0x04
    HDEVINFO = ctypes.c_void_p

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                              ctypes.c_void_p, wt.DWORD]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
    setupapi.SetupDiEnumDeviceInfo.argtypes = [HDEVINFO, wt.DWORD, ctypes.c_void_p]
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
        HDEVINFO, ctypes.c_void_p, wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)]

    class DID(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", ctypes.c_byte * 16),
                    ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]

    def snapshot() -> frozenset[str]:
        found: set[str] = set()
        h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                         DIGCF_PRESENT | DIGCF_ALLCLASSES)
        if not h:
            return frozenset()
        try:
            buf = ctypes.create_unicode_buffer(1024)
            need = wt.DWORD()
            i = 0
            while True:
                d = DID()
                d.cbSize = ctypes.sizeof(DID)
                if not setupapi.SetupDiEnumDeviceInfo(h, i, ctypes.byref(d)):
                    break
                i += 1
                if setupapi.SetupDiGetDeviceInstanceIdW(
                        h, ctypes.byref(d), buf, 1024, ctypes.byref(need)):
                    s = buf.value
                    # USB nodes only; PCI/ACPI churn would drown the signal
                    if s.upper().startswith("USB\\") or "VID_" in s.upper():
                        found.add(s)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(h)
        return frozenset(found)

    end = time.time() + args.seconds
    prev = snapshot()
    log(f"  baseline: {len(prev)} USB nodes")
    log(f"  watching {args.seconds:.0f}s - perform the vendor procedure now")
    log("  (power off, hold Volume Up, connect the cable while holding)")
    events = 0
    while time.time() < end:
        cur = snapshot()
        if cur != prev:
            for gone in sorted(prev - cur):
                log(f"  - GONE    {gone}")
                events += 1
            for new in sorted(cur - prev):
                log(f"  + APPEAR  {new}")
                events += 1
            prev = cur
    log("")
    if events == 0:
        log("  no USB device changed during the window")
    else:
        log(f"  {events} change(s) recorded")
    record("watch", events=events, seconds=args.seconds)
    cp = com_port()
    log(f"  COM port now: {cp or 'none'}")
    return 0


def tablet_on_bus() -> bool:
    """Is the tablet present at all, in ANY of its identities?

    `offcheck` used to ask `pids_present()`, which only looks for VID_05C6 - so a
    tablet wedged as `VID_0000&PID_0002` read as absent, and the one measurement
    that function exists to make could not be taken in the state the tablet is
    actually in. The wedged node counts as present here.
    """
    for inst in _usb_enum():
        up = inst.upper()
        if "VID_05C6" in up or "VID_0000" in up:
            return True
    return False


def cmd_offcheck(args) -> int:
    """Decide whether the tablet is genuinely powered off, from the host side.

    The vendor procedure (docs/43) begins with "power off status", and that is the
    one step nobody can verify: docs/07 sE2 recorded that this tablet "cannot be
    powered off - power always returns to logo, then crashdump", and every cycle in
    this repository has been a key-hold reset.

    But the two states are distinguishable by how long the device stays away:

      key-hold reset  -> absent ~15-16 s, then back as 900E
      genuine off     -> absent indefinitely, and does not come back on its own

    So this watches for absence and reports elapsed time with a verdict. That turns
    "power off the tablet" from a guess into a measured condition, which is what the
    procedure actually needs before the key is pressed.
    """
    threshold = args.threshold
    log("=" * 70)
    log(f"#  offcheck - is the tablet genuinely OFF?")
    log(f"#  threshold {threshold:.0f}s  (a key-hold reset returns in ~16 s)")
    log("=" * 70)

    if tablet_on_bus():
        log("  device is PRESENT - not off.")
        log("  To get an off state: unplug the cable, then hold Power well past the")
        log("  15 s reset point. Watch this window while you do it.")
    else:
        log("  device is already absent; timing the absence now")

    start_absent = None
    deadline = time.time() + args.seconds
    verdict_printed = False
    while time.time() < deadline:
        present = tablet_on_bus()
        now = time.time()
        if present:
            if start_absent is not None:
                away = now - start_absent
                log(f"  + BACK after {away:.1f}s - that is a RESET, not an off state")
                start_absent = None
                verdict_printed = False
            time.sleep(0.1)
            continue

        if start_absent is None:
            start_absent = now
            log("  - absent, timing...")
        away = now - start_absent
        if not verdict_printed and away >= threshold:
            log(f"  *** ABSENT for {away:.0f}s - consistent with a GENUINE OFF STATE ***")
            log("  You can now hold the key and insert the cable.")
            verdict_printed = True
        time.sleep(0.1)

    if start_absent is not None:
        away = time.time() - start_absent
        verdict = "GENUINE OFF" if away >= threshold else "short gap (probably reset)"
        log("")
        log(f"  final: absent {away:.1f}s -> {verdict}")
        record("offcheck", away=round(away, 1), verdict=verdict)
        return 0 if away >= threshold else 1

    log("")
    log("  the device never left the bus during the window")
    record("offcheck", away=0, verdict="never-absent")
    return 1


def cmd_selftest(_args) -> int:
    """Prove the toolchain works without touching the device's state."""
    log("=" * 70)
    log("#  selftest")
    log("=" * 70)
    steps = []

    n = pids_present()
    steps.append(("VID_05C6 enumeration", True, f"{len(n)} node(s)"))
    log(f"  nodes: {list(n.values()) or 'none'}")

    cp = com_port()
    steps.append(("Qualcomm COM port present", cp is not None, cp or "none"))
    log(f"  port: {cp or 'none'}")

    if cp:
        link = None
        try:
            link = Link(cp)
            steps.append(("port opens", True, cp))
            # passive read only - zero writes
            data = link.raw(8, 1.5)
            steps.append(("bytes pending", len(data) > 0,
                          f"{len(data)} B" if data else "none (HELLO spent)"))
            if data:
                cmd, ln = struct.unpack_from("<II", data, 0)
                steps.append(("HELLO readable", cmd == CMD_HELLO_REQ,
                              f"{NAMES.get(cmd, hex(cmd))} len={ln}"))
        except Exception as err:  # noqa: BLE001
            steps.append(("port opens", False, f"{type(err).__name__}"))
        finally:
            if link:
                link.close()

    table = HERE / "last_table.json"
    if table.exists():
        t = json.loads(table.read_text())
        steps.append(("memory table cached", True, f"{len(t)} entries"))
    else:
        steps.append(("memory table cached", False, "none yet"))

    src = HERE / "prog_firehose_ddr.elf"
    melf = Path(r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
                r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf")
    steps.append(("programmer on disk", melf.is_file(),
                  f"{melf.stat().st_size} B" if melf.is_file() else "missing"))

    log("")
    log(f"{'check':<32} {'result':<8} detail")
    log("-" * 70)
    for name, good, detail in steps:
        log(f"{name:<32} {'PASS' if good else 'FAIL':<8} {detail}")
    record("selftest", steps=[(n, g, d) for n, g, d in steps])
    return 0 if all(g for _, g, _ in steps) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="what is on the bus right now")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("wait", help="wait for a mode")
    s.add_argument("--want", default="900e", choices=["900e", "9008", "com"])
    s.add_argument("--seconds", type=float, default=60)
    s.set_defaults(fn=cmd_wait)

    s = sub.add_parser("read", help="read a memory region (needs a fresh HELLO)")
    s.add_argument("--region", default=None, help="substring of the region name")
    s.add_argument("--all", action="store_true")
    s.add_argument("--max", type=int, default=1 << 20)
    s.add_argument("--port", default=None)
    s.add_argument("--hello-timeout", type=float, default=8.0)
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("bump", help="900E -> 9008 and take the 9008 HELLO in the same run")
    s.add_argument("--port", default=None)
    s.add_argument("--no-grab", action="store_true",
                   help="switch only, do not chase the 9008 HELLO afterwards")
    s.add_argument("--edl-timeout", type=float, default=45.0,
                   help="how long to wait for the 9008 node (re-enumeration ~21 s)")
    s.set_defaults(fn=cmd_bump)

    s = sub.add_parser("selftest", help="verify the toolchain, change nothing")
    s.set_defaults(fn=cmd_selftest)

    s = sub.add_parser("catch", help="hold a handle across a power cycle and grab the HELLO")
    s.add_argument("--port", default=None)
    s.add_argument("--seconds", type=float, default=180)
    s.add_argument("--no-bump", action="store_true",
                   help="only report the HELLO, do not switch to EDL on the same handle")
    s.add_argument("--edl-timeout", type=float, default=45.0)
    s.set_defaults(fn=cmd_catch)

    s = sub.add_parser("edl-hello", help="wait for an existing 9008 node and read its HELLO")
    s.add_argument("--timeout", type=float, default=45.0)
    s.set_defaults(fn=cmd_edl_hello)

    s = sub.add_parser("watch", help="log every USB device appearing/disappearing, no VID filter")
    s.add_argument("--seconds", type=float, default=120)
    s.set_defaults(fn=cmd_watch)

    s = sub.add_parser("offcheck", help="is the tablet genuinely OFF? (times the absence)")
    s.add_argument("--seconds", type=float, default=120)
    s.add_argument("--threshold", type=float, default=25.0,
                   help="absence longer than this is treated as a real off state")
    s.set_defaults(fn=cmd_offcheck)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
