#!/usr/bin/env python3
"""
banner_capture.py - upload the programmer, then LISTEN instead of talking.

The idea this script exists for
-------------------------------
Every earlier session sent <configure/> about one millisecond after DONE and then
read the reply. That conflates two possibilities:

  a) the programmer started and printed a banner (VIP status, supported functions),
     but our configure spoiled the FIFO, or
  b) the programmer never started at all.

This script separates them. After DONE it sends NOTHING for a while and only reads.
If a banner appears, the programmer is alive and its strings say what it wants.
If nothing appears, that is a measurement, not a guess.

Result on TB520FU: nothing appears, ever. See docs/05-firehose-and-the-silence.md.

Stages
------
  1. wait for a 05c6 device (tight polling, no long sleeps)
  2. if 900e -> bump to 9008 using the mode-switch sequence
  3. upload the full melf with strict framing, requiring a minimum byte count
  4. DONE
  5. PASSIVE capture: raw reads only, nothing sent
  6. optional active probes, only if asked for

This script does NOT write to storage. It uploads a programmer into RAM and reads.

Usage
-----
  python banner_capture.py --programmer path/to/xbl_s_devprg_ns.melf
  python banner_capture.py --programmer ... --budget 600 --attempts 5
  python banner_capture.py --programmer ... --no-probe

Requirements
------------
  pip install pyusb
  WinUSB driver bound to 05c6:9008 / 05c6:900e
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import usb.core
except ImportError:
    print("pyusb is required:  pip install pyusb", file=sys.stderr)
    raise SystemExit(2)

from sahara_upload import (
    PID_CRASHDUMP,
    PID_EDL,
    Link,
    close_device,
    device_present,
    open_device,
    upload,
)
from sahara_bump import bump_once

#: Sahara never requests the trailing padding, so a complete transfer is less than
#: the file size. This is the count the SM8650 devprg actually yields.
MIN_SENT_DEFAULT = 1_554_996

T0 = time.time()
LOG_PATH: Path | None = None


def log(msg: str) -> None:
    line = f"[{time.time() - T0:8.3f}] {msg}"
    print(line, flush=True)
    if LOG_PATH is not None:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def hexdump(data: bytes, limit: int = 512) -> str:
    data = data[:limit]
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"      {i:04x}  {hexpart:<47}  {text}")
    if len(data) == limit:
        lines.append("      ...")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode switch: crashdump (900e) -> genuine EDL (9008)
# ---------------------------------------------------------------------------
def bump_to_edl(timeout_s: float = 40.0) -> bool:
    """Crashdump -> EDL, delegating to the measured implementation.

    The sequence lives in sahara_bump.py, which is the version with log evidence
    behind it. Duplicating it here once produced a malformed switch packet (the
    command id was embedded twice in the payload), so this is a call, not a copy.
    See docs/14-edl-mode-switch.md.
    """
    return bump_once(timeout_s=timeout_s, do_reset=True)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
def xml(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8" ?><data>{body}</data>'.encode()


PROBES = [
    ("nop", xml("<nop />")),
    ("getstorageinfo", xml("<getstorageinfo />")),
    ("configure + label", xml(
        '<configure MemoryName="ufs" Verbose="1" AlwaysValidate="0" '
        'MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" '
        'ZlpAwareHost="1" SkipStorageInit="0" label="PrimaryGPT" />')),
    ("configure bare", xml('<configure MemoryName="ufs" />')),
]


def passive_capture(link: Link, seconds: float) -> bytes:
    """Read only. Send nothing. Stop 1 s after the last byte arrived."""
    buf = bytearray()
    deadline = time.time() + seconds
    last_data = None
    while time.time() < deadline:
        chunk = link._read_chunk(120)
        if chunk:
            buf += chunk
            last_data = time.time()
            log(f"    passive +{len(chunk)} B")
        if last_data and (time.time() - last_data) > 1.0:
            break
    return bytes(buf)


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------
def session(blob: Path, keep_probing: bool, min_sent: int) -> bool:
    if not device_present(PID_EDL):
        return False

    dev = open_device(PID_EDL)
    if dev is None:
        return False
    link = Link(dev)

    data = blob.read_bytes()
    result = {}
    try:
        result = upload(link, data, min_sent)
    except Exception as exc:  # noqa: BLE001
        log(f"  upload exception {type(exc).__name__}: {exc}")

    if not (result.get("end") == 0 and result.get("status") == "done"):
        log(f"  upload incomplete: {result}")
        close_device(dev)
        return False

    log("  === PASSIVE CAPTURE (nothing sent) ===")
    banner = passive_capture(link, seconds=6.0)

    if banner:
        log(f"  *** BANNER: {len(banner)} B ***")
        log(hexdump(banner))
        text = banner.decode("utf-8", "replace")
        for key in ("VIP", "firehose", "Sahara", "supported_functions",
                    "MemoryName", "ERROR", "configure"):
            if key.lower() in text.lower():
                log(f"  >>> banner mentions: {key}")
        close_device(dev)
        return True

    log("  banner: NOTHING (programmer silent)")

    if not keep_probing:
        close_device(dev)
        return False

    answered = False
    for name, payload in PROBES:
        if not device_present(PID_EDL):
            log(f"  device gone before probe '{name}' -> programmer reset")
            break
        log(f"  --- probe: {name} ---")
        if not link.write(payload, zlp=False):
            log("    write refused")
            continue
        rsp = link.read_packet(2500, retries=1)
        if rsp:
            answered = True
            log(f"    *** {len(rsp)} B ***")
            log(hexdump(rsp))
        else:
            log("    silence")

    close_device(dev)
    return answered


def main(argv: list[str] | None = None) -> int:
    global LOG_PATH

    ap = argparse.ArgumentParser(
        description="Upload a programmer, then listen instead of talking.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--programmer", required=True, type=Path,
                    help="path to the .melf programmer")
    ap.add_argument("--budget", type=float, default=420.0,
                    help="seconds to wait for the device to appear (default 420)")
    ap.add_argument("--attempts", type=int, default=3,
                    help="number of full attempts (default 3)")
    ap.add_argument("--no-bump", action="store_true",
                    help="do not touch 900e; only use 9008")
    ap.add_argument("--no-probe", action="store_true",
                    help="passive capture only, no XML probes")
    ap.add_argument("--min-sent", type=int, default=MIN_SENT_DEFAULT,
                    help=f"minimum bytes for a valid transfer "
                         f"(default {MIN_SENT_DEFAULT})")
    ap.add_argument("--log", type=Path, default=None,
                    help="log file path (default: next to the programmer)")
    args = ap.parse_args(argv)

    if not args.programmer.is_file():
        print(f"ERROR: no such file: {args.programmer}")
        return 2

    LOG_PATH = args.log or args.programmer.parent / "banner_capture.log"
    LOG_PATH.write_text("", encoding="utf-8")

    log("############################################################")
    log("#  Programmer banner capture - listen, do not talk          #")
    log("############################################################")
    log(f"programmer: {args.programmer.name}  "
        f"{args.programmer.stat().st_size} B")
    log(f"waiting for a 05c6 device (budget {args.budget:.0f}s)...")

    deadline = time.time() + args.budget
    while time.time() < deadline:
        if device_present(PID_EDL):
            break
        if device_present(PID_CRASHDUMP) and not args.no_bump:
            break
        time.sleep(0.05)

    for attempt in range(1, args.attempts + 1):
        log(f"===== attempt {attempt}/{args.attempts} =====")

        if not device_present(PID_EDL) and not device_present(PID_CRASHDUMP):
            log("  no device; waiting 30 s for the next boot cycle")
            time.sleep(30)
            continue

        if device_present(PID_CRASHDUMP) and not args.no_bump:
            if not bump_to_edl():
                log("  mode switch failed")
                continue

        if not device_present(PID_EDL):
            log("  no 9008")
            continue

        try:
            if session(args.programmer, not args.no_probe, args.min_sent):
                log("")
                log("#############################################################")
                log("#  PROGRAMMER IS ALIVE - it answered after DONE             #")
                log("#############################################################")
                return 0
        except Exception as exc:  # noqa: BLE001
            log(f"  session exception {type(exc).__name__}: {exc}")

        log("  attempt finished without an answer")

    log("")
    log("=== NO ANSWER IN ANY ATTEMPT ===")
    log("The programmer accepts the image (END 0x0, DONE) but never speaks on USB.")
    log("See docs/05-firehose-and-the-silence.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
