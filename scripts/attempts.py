"""attempts.py - the ledger the goal's word "repeatable" actually requires.

Why this exists
---------------
The objective is not "reach EDL once". It is: *repeatable, documented* acquisition of
`05C6:9008` with `HELLO ver=3 mode=0`. A single success does not satisfy that, and this
repository has no way to tell one-off luck from a working method - attempts have been
described in prose documents, each session with its own narrative, and never counted.

So: one line per physical attempt, appended, with the conditions that were varied and the
outcome that was observed. Then a summary that answers the only question that matters:

    given N attempts at method M, how many produced the goal state?

What counts as success
----------------------
A row is `success` only if a HELLO was actually read with `ver=3, mode=0`. That is
stricter than "a 9008 node appeared", and deliberately so: the 9008 node alone can be
mute (docs/05 §3, the zombie state), and a mute node cannot load a programmer. Where the
tooling captured the packet, the capture path is recorded so the claim is re-checkable
(docs/97, docs/102).

Usage
    python attempts.py --add --route catch --keys none --outcome success --note "..."
    python attempts.py --add --route short --keys none --outcome wedge --orientation A
    python attempts.py --summary
    python attempts.py --show
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "attempts.jsonl"
CAPTURES = HERE / "hello_captures"

ROUTES = ("catch", "short", "bump", "manual")
OUTCOMES = ("success", "9008-mute", "900e", "wedge", "absent", "aborted")


def log(m: str = "") -> None:
    print(m, flush=True)


def last_capture(within_seconds: float = 300.0) -> str | None:
    """The newest HELLO capture, but only if it is recent.

    The window matters. Taking simply "the newest file" means a success recorded after a
    failed attempt inherits the *previous* attempt's packet, and then the ledger's most
    important field is evidence for the wrong event. A capture older than a few minutes
    cannot belong to the attempt being recorded now, so it is not offered.
    """
    if not CAPTURES.is_dir():
        return None
    files = sorted(CAPTURES.glob("*.bin"))
    if not files:
        return None
    newest = files[-1]
    age = time.time() - newest.stat().st_mtime
    return newest.name if age <= within_seconds else None


def capture_goal_state(name: str) -> bool | None:
    """Did that capture actually hold ver=3 mode=0? None if it cannot be checked."""
    meta = CAPTURES / name.replace(".bin", ".json")
    if not meta.is_file():
        return None
    try:
        d = json.loads(meta.read_text())
    except Exception:  # noqa: BLE001
        return None
    return bool(d.get("is_goal_state"))


def add(args) -> int:
    if args.outcome not in OUTCOMES:
        log(f"outcome must be one of: {', '.join(OUTCOMES)}")
        return 2
    if args.route not in ROUTES:
        log(f"route must be one of: {', '.join(ROUTES)}")
        return 2

    capture = args.capture or (last_capture() if args.outcome == "success" else None)
    row = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "route": args.route,
        "keys": args.keys,
        "orientation": args.orientation,
        "outcome": args.outcome,
        "hello_ver": args.ver,
        "hello_mode": args.mode,
        "capture": capture,
        "note": args.note or "",
    }

    # A success claim must be backed by a capture that says so. If the packet was not
    # saved, the row is downgraded rather than trusted - "I saw ver=3 mode=0" with no
    # bytes is exactly the unverifiable claim docs/97 was written about.
    if row["outcome"] == "success":
        if not capture:
            log("  no HELLO capture found; recording as '9008-mute' not 'success'")
            log("  (a goal-state claim needs the packet on disk - docs/97)")
            row["outcome"] = "9008-mute"
        else:
            verdict = capture_goal_state(capture)
            if verdict is False:
                log(f"  capture {capture} is NOT ver=3 mode=0; recording as '9008-mute'")
                row["outcome"] = "9008-mute"
            elif verdict is None:
                log(f"  capture {capture} has no sidecar; cannot verify - keeping claim")
                log("  as 'success' but the evidence is weaker than it should be")

    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    log(f"recorded: {row['when']}  route={row['route']} keys={row['keys']} "
        f"-> {row['outcome']}")
    return 0


def load() -> list[dict]:
    if not LEDGER.is_file():
        return []
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return rows


def summary(_args) -> int:
    rows = load()
    if not rows:
        log("no attempts recorded yet - the ledger is empty")
        log("a claim of repeatability needs at least two rows here")
        return 1

    log("=" * 72)
    log("#  Attempts ledger")
    log("=" * 72)
    log(f"  total attempts: {len(rows)}")
    log(f"  first: {rows[0]['when']}    last: {rows[-1]['when']}")
    log("")

    by_route: dict[str, list[dict]] = {}
    for r in rows:
        by_route.setdefault(r.get("route", "?"), []).append(r)

    log(f"  {'route':10s} {'keys':10s} {'attempts':>8s} {'success':>8s} {'rate':>7s}")
    log("  " + "-" * 48)
    for route in sorted(by_route):
        rs = by_route[route]
        for keys in sorted({r.get("keys", "?") for r in rs}):
            sub = [r for r in rs if r.get("keys", "?") == keys]
            wins = sum(1 for r in sub if r.get("outcome") == "success")
            rate = f"{100 * wins / len(sub):.0f}%"
            log(f"  {route:10s} {keys:10s} {len(sub):>8d} {wins:>8d} {rate:>7s}")
    log("")

    wins = [r for r in rows if r.get("outcome") == "success"]
    log(f"  goal-state successes: {len(wins)}")
    if len(wins) >= 2:
        routes = {r["route"] for r in wins}
        log(f"  reached by route(s): {', '.join(sorted(routes))}")
        log("")
        log("  *** REPEATABLE: more than one independent success is recorded. ***")
    elif len(wins) == 1:
        log("  one success is NOT repeatability - repeat the same method and add a row")
    else:
        log("  no success yet; the goal state has not been observed")
    return 0


def show(_args) -> int:
    rows = load()
    if not rows:
        log("ledger empty")
        return 1
    log(f"{'when':20s} {'route':8s} {'keys':10s} {'orientation':12s} outcome")
    log("-" * 74)
    for r in rows:
        log(f"{r['when']:20s} {r.get('route',''):8s} {r.get('keys',''):10s} "
            f"{str(r.get('orientation') or ''):12s} {r['outcome']}"
            f"{('  ' + r['note']) if r.get('note') else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--route", default="catch", help="catch | short | bump | manual")
    ap.add_argument("--keys", default="none", help="none | volup | voldown | both")
    ap.add_argument("--orientation", default=None, help="A or B, for a D+ short")
    ap.add_argument("--outcome", default="wedge", help=" | ".join(OUTCOMES))
    ap.add_argument("--ver", type=int, default=None)
    ap.add_argument("--mode", type=int, default=None)
    ap.add_argument("--capture", default=None)
    ap.add_argument("--note", default=None)
    args = ap.parse_args()

    if args.summary:
        return summary(args)
    if args.show:
        return show(args)
    if args.add:
        return add(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
