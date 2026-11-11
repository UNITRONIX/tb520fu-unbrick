"""preflight.py - check every precondition for a physical attempt, in one command.

Why this exists
---------------
Each physical attempt costs a power cycle, a hand on the tablet, and a few minutes. In this
project several attempts were spent on conditions that could have been checked from the desk
in advance:

  * the cable was in a socket whose 9008 identity is bound to libwdi WinUSB, so no COM port
    could ever appear (docs/105) - the run would have reported "no port" and the ledger
    would have recorded a device failure;
  * a stale process still held the port, so the HELLO was consumed before the new session
    opened it (docs/34);
  * the programmer file was missing from the ROM directory, which is only discovered at
    upload time, after the handshake has already been spent.

So: one command that asserts the preconditions and prints the single next action. It does
not touch the device - it only reads.

Exit code is 0 only when every precondition that can be checked from the desk passes.

Usage
    python preflight.py
    python preflight.py --expect 900e
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tablet as T  # noqa: E402
import driver_check as D  # noqa: E402

ROM = Path(r"C:\ProgramData\RSA\Download\RomFiles"
           r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
           r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929")
MELF = ROM / r"image\xbl_s_devprg_ns.melf"


class Check:
    def __init__(self, name: str, ok: bool, detail: str, fix: str = "") -> None:
        self.name, self.ok, self.detail, self.fix = name, ok, detail, fix


def holding_processes() -> list[str] | None:
    """Processes that could be holding a Qualcomm COM port open; None if unknown.

    Returns None - not [] - when the query itself fails. An empty list means "measured,
    nothing there"; None means "could not look". Collapsing the two is how a check that
    always passes gets written: the first version of this function built the PowerShell
    command inline with escaped quotes, PowerShell received a broken command line, every
    CommandLine came back empty, and the result read as a clean "none detected" while
    nothing had actually been inspected.

    The query is written to a file for the same reason: no escaping, no surprises.
    """
    script = HERE / "_holders.ps1"
    try:
        script.write_text(
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -like 'python*' } | "
            "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }\n",
            encoding="utf-8")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script)],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return None
        raw = proc.stdout
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            script.unlink()
        except OSError:
            pass

    out: list[str] = []
    seen_any = False
    for line in raw.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        seen_any = True
        pid, cmd = line.split("|", 1)
        low = cmd.lower()
        if "preflight" in low or "driver_check" in low:
            continue
        if any(k in low for k in ("tablet.py", "catch", "grab", "sahara",
                                  "short_attempt", "ab_test", "attempts.py")):
            out.append(f"{pid.strip()}: {cmd.strip()[:90]}")
    # If the query ran but produced no parsable rows at all, treat it as unknown rather
    # than as a clean pass.
    if not seen_any:
        return None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", default=None, choices=["900e", "9008"],
                    help="the mode this attempt is aiming for; affects the advice only")
    args = ap.parse_args()

    checks: list[Check] = []

    # --- 1. what is on the bus right now ------------------------------------
    pids = T.pids_present()
    com = T.com_port()
    ids = sorted(set(pids.values()))
    if not ids:
        checks.append(Check("device on the bus", False,
                            "no VID_05C6 node - the tablet is off, wedged, or unplugged",
                            "Power 20-30 s, then plug in with NO keys held"))
        wedged = any("VID_0000" in n.upper() for n in T._usb_enum())
        if wedged:
            checks.append(Check("wedged node present", False,
                                "VID_0000&PID_0002 (null descriptor) - not clearable from the host",
                                "power removal is the only way (docs/103)"))
    else:
        checks.append(Check("device on the bus", True, f"PID {', '.join(ids)}"))
        if "9008" in ids:
            checks.append(Check("mode", True, "9008 - this is the EDL state"))
        elif "900E" in ids:
            checks.append(Check("mode", True, "900E - crashdump; a bump is needed",
                                "python tablet.py catch --seconds 180"))

    # --- 2. can this SOCKET expose a COM port? ------------------------------
    rows = D.rows()
    if not rows:
        checks.append(Check("driver binding", False, "no tablet instance recorded yet",
                            "first plug on a new socket creates it - check again after"))
    else:
        # The binding that matters is the one for the socket the cable is in. When a
        # live node exists we know its location, so report THAT row; otherwise report
        # every readable socket so the operator can choose one.
        loc = None
        for inst in T._usb_enum():
            up = inst.upper()
            if "VID_05C6" in up or "VID_0000" in up:
                for r in rows:
                    if r["instance"].upper() == up:
                        loc = r["location"]
                        break
        live = [r for r in rows if loc and r["location"] == loc]
        pool = live if live else [r for r in rows if r["serial"]]
        if live:
            good = any(r["serial"] for r in live)
            checks.append(Check(
                "driver binding on this socket", good,
                f"{loc} -> {live[0]['driver']}" + (f", {live[0]['com']}" if live[0]["com"] else ""),
                "Switch-DeviceDriver.ps1 -To COM (elevated) - with WinUSB no COM port exists"))
        else:
            checks.append(Check(
                "driver binding", True,
                f"{len(pool)} readable socket(s): "
                + ", ".join(f"{r['location']}({r['com'] or '-'})" for r in pool[:4]),
                ""))

    # --- 3. nobody else is holding the port ---------------------------------
    holders = holding_processes()
    if holders is None:
        checks.append(Check("no stale port holder", False,
                            "could not query processes - unknown, not clear",
                            "run it by hand: a leftover catcher eats the HELLO"))
    else:
        checks.append(Check("no stale port holder", not holders,
                            "; ".join(holders) if holders else "none",
                            "kill the process before plugging in - it will eat the HELLO"))

    # --- 4. the programmer is on disk ---------------------------------------
    if MELF.is_file():
        checks.append(Check("programmer on disk", True, f"{MELF.stat().st_size} B"))
    else:
        checks.append(Check("programmer on disk", False, f"missing: {MELF}",
                            "the handshake would be spent with nothing to upload"))

    # --- 5. ledger health ----------------------------------------------------
    try:
        import attempts as A
        n = len(A.load())
        checks.append(Check("attempts ledger", True, f"{n} row(s) recorded"))
    except Exception as err:  # noqa: BLE001
        checks.append(Check("attempts ledger", False, f"{type(err).__name__}"))

    # --- report -------------------------------------------------------------
    print("=" * 78)
    print("#  preflight")
    print("=" * 78)
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        print(f"  {'PASS' if c.ok else 'FAIL':4s} {c.name:{width}s} {c.detail}")
        if not c.ok and c.fix:
            print(f"       {' ':{width}s} -> {c.fix}")

    failures = [c for c in checks if not c.ok]
    print()
    if not failures:
        print("  All desk-side preconditions pass. Make the physical attempt now.")
        if com:
            print(f"  A COM port is already up: {com}")
        print("  Then: python tablet.py catch --seconds 180")
    else:
        print(f"  {len(failures)} precondition(s) fail. Fix these BEFORE the cable goes in:")
        for c in failures:
            print(f"    - {c.name}: {c.fix or c.detail}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
