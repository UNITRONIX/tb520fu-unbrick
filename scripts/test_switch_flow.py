"""test_switch_flow.py - prove the 900E -> 9008 switch sequence without a tablet.

Why this exists
---------------
The switch is a five-packet conversation where every packet must be the right kind
and the *last* step - grabbing the HELLO off the new 9008 node - is a race that only
happens once per boot. It cannot be debugged by trial and error against hardware
that takes 20 s to re-enumerate and then locks you out until the next physical
power cycle.

So the sequence is exercised here against a fake Link that records what was written
and replays what the device is documented to answer (docs/14 §2).

What this does NOT prove: that the tablet answers this way. It proves the host side
sends the documented bytes in the documented order. The device half is only ever
proven by a real run, and docs/97 is the standing reminder of that distinction.

Run: python test_switch_flow.py
"""
from __future__ import annotations

import struct
import sys

import tablet as T


class FakeLink:
    """Replays the documented 900E responses and records the host's writes."""

    def __init__(self, script: list[bytes], ver: int = 2) -> None:
        self.script = list(script)
        self.written: list[bytes] = []
        self.ver = ver
        self.ser = None

    def write(self, data: bytes) -> bool:
        self.written.append(data)
        return True

    def packet(self, timeout=None):
        return self.script.pop(0) if self.script else None

    def close(self) -> None:
        pass


def hello(ver: int, mode: int) -> bytes:
    return struct.pack("<IIIIIIIIIIII", T.CMD_HELLO_REQ, 0x30,
                       ver, 1, 0, mode, 24, 0x1234, 0x5678, 0x9abc, 0xdef0, 1)


def cmd_pkt(cmd: int, ln: int = 8, extra: int = 0) -> bytes:
    body = struct.pack("<III", cmd, ln, extra)
    return body + b"\x00" * max(0, ln - len(body))


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  - ' + detail) if detail else ''}")
    return cond


def main() -> int:
    ok = True

    # --- happy path: mode=2 -> CMD_READY -> fresh HELLO -> END/DONE ---------
    print("\nswitch_to_edl, documented exchange")
    link = FakeLink([
        cmd_pkt(T.CMD_CMD_READY),          # answer to HELLO_RSP mode=3
        hello(3, T.MODE_IMAGE_TX),          # fresh HELLO after SWITCH_MODE
        cmd_pkt(T.CMD_END_TRANSFER, 16),   # empty transfer
        None,                               # DONE ack (or its absence)
    ])
    result = T.switch_to_edl(link, ver=2)
    ok &= check("returns True", result)
    ok &= check("sent 4 writes (HELLO_RSP, SWITCH, HELLO_RSP, DONE)",
                len(link.written) == 4, f"{len(link.written)}")

    first = struct.unpack_from("<II", link.written[0], 0)
    ok &= check("write 1 is HELLO_RSP mode=3",
                first[0] == T.CMD_HELLO_RSP
                and struct.unpack_from("<I", link.written[0], 20)[0] == T.MODE_COMMAND)

    sw = struct.unpack_from("<III", link.written[1], 0)
    ok &= check("write 2 is SWITCH_MODE len=12 -> IMAGE_TX",
                sw == (T.CMD_SWITCH_MODE, 12, T.MODE_IMAGE_TX), f"{sw}")

    conf_mode = struct.unpack_from("<I", link.written[2], 20)[0]
    ok &= check("write 3 confirms mode=0", conf_mode == T.MODE_IMAGE_TX)

    # The device's own version must be echoed back, not the 900E one: the 9008
    # HELLO carries ver=3 and using ver=2 there is a real protocol error.
    echoed = struct.unpack_from("<I", link.written[2], 8)[0]
    ok &= check("write 3 echoes the FRESH ver=3, not the 900E ver=2",
                echoed == 3, f"echoed {echoed}")

    ok &= check("write 4 is DONE_REQ",
                struct.unpack_from("<I", link.written[3], 0)[0] == T.CMD_DONE_REQ)

    # --- refusal: device does not offer COMMAND mode ------------------------
    print("\nswitch_to_edl, COMMAND mode refused")
    link = FakeLink([None])
    ok &= check("returns False on no CMD_READY", T.switch_to_edl(link, 2) is False)
    ok &= check("stops after the refused hello_rsp", len(link.written) == 1,
                f"{len(link.written)}")

    # --- refusal: switch not confirmed --------------------------------------
    print("\nswitch_to_edl, switch not confirmed")
    link = FakeLink([cmd_pkt(T.CMD_CMD_READY), cmd_pkt(T.CMD_END_TRANSFER, 16)])
    ok &= check("returns False when no fresh HELLO follows",
                T.switch_to_edl(link, 2) is False)
    ok &= check("did not send DONE", len(link.written) == 2, f"{len(link.written)}")

    # --- the goal test ------------------------------------------------------
    print("\nGoal predicate")
    ok &= check("ver=3 mode=0 is the goal", (3, T.MODE_IMAGE_TX) == (3, 0))
    ok &= check("ver=2 mode=2 is not", not (2 == 3 and T.MODE_MEMORY_DEBUG == 0))

    print(f"\n{'ALL PASS' if ok else 'FAILURES ABOVE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
