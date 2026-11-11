"""test_attempts.py - the ledger must refuse an unbacked success claim.

The one property worth testing here is negative: `--add --outcome success` must NOT be
recorded as a success when there is no capture, or when the capture says something else.
Otherwise the ledger becomes a place to type "it worked", which is precisely the failure
mode docs/97 documented for this project's evidence.

Run: python test_attempts.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import attempts as A


def setup_sandbox() -> Path:
    d = Path(tempfile.mkdtemp(prefix="attempts-test-"))
    (d / "hello_captures").mkdir()
    return d


def with_sandbox(d: Path):
    A.LEDGER = d / "attempts.jsonl"
    A.CAPTURES = d / "hello_captures"


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  - ' + detail) if detail else ''}")
    return cond


def main() -> int:
    ok = True
    real_ledger, real_caps = A.LEDGER, A.CAPTURES
    d = setup_sandbox()
    try:
        with_sandbox(d)

        # 1. success with no capture at all -> downgraded
        print("\nno capture present")
        class Args:
            pass
        a = Args()
        a.route, a.keys, a.orientation = "catch", "none", None
        a.outcome, a.ver, a.mode, a.capture, a.note = "success", 3, 0, None, ""
        A.add(a)
        rows = A.load()
        ok &= check("success without a capture becomes 9008-mute",
                    rows and rows[-1]["outcome"] == "9008-mute",
                    rows[-1]["outcome"] if rows else "no rows")

        # 2. success with a capture that is NOT the goal state -> downgraded
        print("\ncapture exists but is mode=2")
        cap = A.CAPTURES / "20260101-000000-catch.bin"
        cap.write_bytes(b"\x01\x00\x00\x00")
        (A.CAPTURES / "20260101-000000-catch.json").write_text(
            json.dumps({"is_goal_state": False, "version": 2, "mode": 2}))
        a2 = Args()
        a2.route, a2.keys, a2.orientation = "catch", "none", None
        a2.outcome, a2.ver, a2.mode, a2.capture, a2.note = "success", 3, 0, None, ""
        A.add(a2)
        rows = A.load()
        ok &= check("success with a mode=2 capture becomes 9008-mute",
                    rows[-1]["outcome"] == "9008-mute", rows[-1]["outcome"])

        # 3. success with a genuine goal-state capture -> kept
        print("\ncapture IS ver=3 mode=0")
        cap2 = A.CAPTURES / "20260101-000001-catch.bin"
        cap2.write_bytes(b"\x01\x00\x00\x00")
        (A.CAPTURES / "20260101-000001-catch.json").write_text(
            json.dumps({"is_goal_state": True, "version": 3, "mode": 0}))
        a3 = Args()
        a3.route, a3.keys, a3.orientation = "catch", "none", None
        a3.outcome, a3.ver, a3.mode, a3.capture, a3.note = "success", 3, 0, None, ""
        A.add(a3)
        rows = A.load()
        ok &= check("verified capture keeps 'success'", rows[-1]["outcome"] == "success",
                    rows[-1]["outcome"])
        ok &= check("the capture is recorded on the row", bool(rows[-1]["capture"]))

        # 4. summary maths
        print("\nsummary")
        A.summary(None)
        rows = A.load()
        ok &= check("3 rows recorded", len(rows) == 3, str(len(rows)))
        wins = [r for r in rows if r["outcome"] == "success"]
        ok &= check("exactly 1 verified success", len(wins) == 1, str(len(wins)))
    finally:
        A.LEDGER, A.CAPTURES = real_ledger, real_caps
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n{'ALL PASS' if ok else 'FAILURES ABOVE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
