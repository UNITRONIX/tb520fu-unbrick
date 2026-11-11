"""compact_sessions.py - collapse repeated identical status polls in the session log.

Why
---
On 2026-11-11 `tablet.py status` was called about twenty times while the device sat
in one unchanged state, and each call wrote a `status` line. The log is the only
history the next session will read, and twenty identical rows bury the handful of
entries that carry a result.

`tablet.py` now refuses to append a `status` line identical to the previous one, so
this cannot recur. This script cleans up what was already written: it keeps the
first entry of any run of identical status records, and it never touches any other
kind of event.

Usage
    python compact_sessions.py            # report only
    python compact_sessions.py --write    # rewrite the file
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LOG = Path(__file__).resolve().parent / "tablet_sessions.jsonl"


def key_of(rec: dict) -> tuple:
    """A status record is 'the same' if its payload matches; everything else is unique."""
    if rec.get("event") == "status":
        return ("status", json.dumps(rec.get("pids"), sort_keys=True), rec.get("com"))
    return ("other", id(rec))   # unique, so other events are never collapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if not LOG.exists():
        print(f"no log at {LOG}")
        return 1

    lines = [ln for ln in LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept: list[str] = []
    dropped = 0
    prev_key = None
    for ln in lines:
        try:
            rec = json.loads(ln)
        except Exception:  # noqa: BLE001
            kept.append(ln)      # never drop a line we cannot parse
            prev_key = None
            continue
        k = key_of(rec)
        if k[0] == "status" and k == prev_key:
            dropped += 1
            continue
        kept.append(ln)
        prev_key = k

    print(f"records before : {len(lines)}")
    print(f"records after  : {len(kept)}")
    print(f"dropped        : {dropped} repeated identical status entries")

    if args.write and dropped:
        LOG.write_text("\n".join(kept) + "\n", encoding="utf-8")
        print(f"rewritten: {LOG}")
    elif dropped:
        print("run with --write to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
