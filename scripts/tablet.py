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


def record(event: str, **kv) -> None:
    """Append one line to the session log so a working procedure is reproducible."""
    rec = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kv}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ---- device presence -----------------------------------------------------
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
    """{instance: pid} for every present VID_05C6 node, via SetupAPI."""
    out: dict[str, str] = {}
    try:
        raw = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_05C6'}"
             " | ForEach-Object {$_.InstanceId + '|' + $_.Status}"],
            capture_output=True, text=True, timeout=25).stdout
    except Exception:  # noqa: BLE001
        return out
    for line in raw.splitlines():
        line = line.strip()
        if "VID_05C6" not in line.upper():
            continue
        inst = line.split("|")[0]
        up = inst.upper()
        i = up.find("PID_")
        out[inst] = up[i + 4:i + 8] if i >= 0 else "?"
    return out


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
    """900E -> 9008. Requires being the first reader of the HELLO."""
    link = open_900e(args.port)
    if link is None:
        return 1
    log(f"  opened {link.port}")
    ok = False
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
            log("  already IMAGE_TX; nothing to switch")
            ok = True
            return 0

        link.write(hello_rsp(ver, MODE_COMMAND))
        r = link.packet(4.0)
        if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_CMD_READY:
            log("  COMMAND mode refused")
            record("bump", ok=False, reason="no-cmd-ready")
            return 1
        log("  CMD_READY")

        link.write(struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX))
        r = link.packet(5.0)
        if r is None or struct.unpack_from("<I", r, 0)[0] != CMD_HELLO_REQ:
            log("  switch not confirmed by a fresh HELLO")
            record("bump", ok=False, reason="switch-refused")
            return 1
        log("  fresh HELLO after switch - confirming")

        link.write(hello_rsp(struct.unpack_from("<I", r, 8)[0], MODE_IMAGE_TX))
        r = link.packet(5.0)
        if r is not None and struct.unpack_from("<I", r, 0)[0] == CMD_END_TRANSFER:
            st = struct.unpack_from("<I", r, 12)[0] if len(r) >= 16 else -1
            log(f"  END status={st:#x} - sending DONE")
            link.write(struct.pack("<II", CMD_DONE_REQ, 8))
            link.packet(3.0)
        log("  switch complete; 9008 should enumerate in ~20 s")
        ok = True
        record("bump", ok=True)
        return 0
    finally:
        link.close()
        if not ok:
            log("  NOTE: the port was closed without a reset on purpose (docs/34)")


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
    try:
        while time.time() < deadline:
            if link is None:
                try:
                    link = Link(port)
                    log(f"  handle open (death #{deaths})")
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
            record("catch", ok=True, ver=ver, mode=mode, deaths=deaths)
            if mode == MODE_MEMORY_DEBUG:
                log("  crashdump HELLO. Run `bump` now, or `read` for memory.")
            elif mode == MODE_IMAGE_TX:
                log("  IMAGE_TX - this is already the EDL state the goal wants.")
            return 0

        log(f"  {args.seconds:.0f}s elapsed with no HELLO")
        record("catch", ok=False, reason="timeout", deaths=deaths)
        return 1
    finally:
        if link:
            link.close()          # never a reset - see Link.close()


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

    s = sub.add_parser("bump", help="900E -> 9008 (needs a fresh HELLO)")
    s.add_argument("--port", default=None)
    s.set_defaults(fn=cmd_bump)

    s = sub.add_parser("selftest", help="verify the toolchain, change nothing")
    s.set_defaults(fn=cmd_selftest)

    s = sub.add_parser("catch", help="hold a handle across a power cycle and grab the HELLO")
    s.add_argument("--port", default=None)
    s.add_argument("--seconds", type=float, default=180)
    s.set_defaults(fn=cmd_catch)

    s = sub.add_parser("watch", help="log every USB device appearing/disappearing, no VID filter")
    s.add_argument("--seconds", type=float, default=120)
    s.set_defaults(fn=cmd_watch)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
