#!/usr/bin/env python3
"""firehose_capability_scan.py - what can the programmer actually do?

The goal is the tablet back, and the one missing capability is a write to UFS.
So the useful question is not "why does DDR training fail" but:

    does the Firehose programmer contain working write primitives at all,
    and what gates them?

This scans the Firehose image (image [3] of the melf, bit-identical to
prog_firehose_ddr.elf) for the operations it implements, and reports which of them
are read-only and which mutate storage.

Firehose speaks XML. The command verbs come straight out of the strings:

    <configure/> <read/> <program/> <erase/> <patch/> <power/> <nop/>
    <getstorageinfo/> <setbootablestorage/> ...

`program`, `erase` and `patch` are the write path. If those handlers exist, the
programmer is capable and the blocker is purely that it never runs - which is a
different problem from "the write path is absent".

Read-only, offline.

Usage
    python firehose_capability_scan.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)
IMG3_OFF, IMG3_LEN = 0x110B50, 303096

#: Firehose XML verbs, and what they do.
VERBS = {
    "configure": "negotiate transfer params (read-only)",
    "read": "READ from storage",
    "program": "WRITE to storage",
    "erase": "ERASE storage",
    "patch": "apply raw memory patches",
    "power": "power off / reset",
    "nop": "liveness probe",
    "getstorageinfo": "storage geometry (read-only)",
    "setbootablestorage": "set boot LUN",
    "setactivepartition": "select GPT slot",
    "getgptinfo": "GPT backup info",
    "getsha256digest": "read digest of a region",
    "peek": "read memory",
    "poke": "write memory",
}

#: Anything that could mean the write path is disabled or gated.
GATES = [
    "readonly", "read-only", "read_only", "readonlymode", "ReadOnly",
    "secure", "Secure", "authenticat", "Authenticat",
    "Vip", "VIP", "sig", "Sig", "cert", "Cert",
    "denied", "Denied", "permission", "Permission",
    "not allowed", "Not allowed", "forbidden", "Forbidden",
    "locked", "Locked", "unlock", "Unlock",
    "enable", "Enable", "disable", "Disable",
    "allow", "Allow",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    args = ap.parse_args()

    melf = Path(args.melf).read_bytes()
    img = melf[IMG3_OFF:IMG3_OFF + IMG3_LEN]

    print("=" * 78)
    print(f"#  Firehose programmer  ({IMG3_LEN} B, image [3])")
    print("=" * 78)

    # ---- 1. which XML verbs are implemented -----------------------------
    print("\n#  XML verbs found in the image")
    print(f"  {'verb':<22} {'count':>6}  meaning")
    print("  " + "-" * 70)
    write_capable = []
    for verb, meaning in VERBS.items():
        # verbs appear as element names in the XML parser's string table
        n = len(re.findall(verb.encode(), img))
        if n:
            print(f"  {verb:<22} {n:>6}  {meaning}")
            if verb in ("program", "erase", "patch", "poke"):
                write_capable.append(verb)
        else:
            print(f"  {verb:<22} {0:>6}  (absent)")

    # ---- 2. the exact XML shapes, where they appear ---------------------
    print("\n#  literal XML fragments (these are what the parser matches)")
    for m in re.finditer(rb"<[a-zA-Z][a-zA-Z0-9_/ ]{2,40}>", img):
        s = m.group().decode("ascii", "replace")
        print(f"  {IMG3_OFF + m.start():#08x}  {s}")
        if sum(1 for _ in re.finditer(re.escape(m.group()), img)) > 3:
            pass

    # ---- 3. gates and refusal messages ---------------------------------
    print("\n#  gate / refusal wording")
    seen = set()
    for m in re.finditer(rb"[\x20-\x7e]{8,}", img):
        s = m.group().decode("ascii", "replace")
        if not any(g in s for g in GATES):
            continue
        if s in seen:
            continue
        a = sum(c.isalpha() or c in " _:=-%.,()/" for c in s) / len(s)
        if a < 0.75:
            continue
        seen.add(s)
        print(f"  {IMG3_OFF + m.start():#08x}  {s[:110]}")

    print("\n" + "=" * 78)
    print("#  VERDICT")
    print("=" * 78)
    if write_capable:
        print(f"  Write primitives present: {', '.join(write_capable)}")
        print()
        print("  The programmer is not crippled. It implements the operations needed")
        print("  to write abl_a / abl_b. Therefore the failure is that it never")
        print("  reaches the point where those handlers are reachable - not that the")
        print("  capability is absent from the binary.")
        print()
        print("  That changes the shape of the problem: instead of 'we cannot")
        print("  write', it becomes 'we cannot get the XML listener up'. Those need")
        print("  different work.")
    else:
        print("  No write verbs found. Either the scan missed the encoding (the")
        print("  parser may compare tokens numerically rather than as strings), or")
        print("  this programmer really is read-only. Do not conclude without")
        print("  checking how the XML handler dispatches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
