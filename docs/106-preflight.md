# Preflight: the preconditions, checked before the cable goes in

A physical attempt costs a power cycle, a hand on the tablet and a few minutes. Several in
this project were spent on conditions that could have been checked from the desk.

---

## 1. The three that actually bit

| what went wrong | how it appeared | cost |
|---|---|---|
| cable in a socket bound to libwdi WinUSB (`docs/105`) | "no port" → read as a device fault | a power cycle, a false ledger row |
| the socket's binding differs from the previous socket's | "it worked last time" | a second power cycle |
| a leftover catcher holding the port (`docs/34`) | silence, i.e. "the HELLO was spent" | a third |

Each of them makes the run *look* like the device failed. None of them is a device failure.
`scripts/preflight.py` checks all of them plus two more (programmer present, ledger readable)
and prints the one action to take.

## 2. What it says right now

```
FAIL device on the bus      no VID_05C6 node
FAIL wedged node present    VID_0000&PID_0002 (null descriptor)
PASS driver binding         2 readable socket(s): Port_#0004.Hub_#0004(COM9),
                                                Port_#0002.Hub_#0002(COM10)
PASS no stale port holder   none
PASS programmer on disk     1569028 B
PASS attempts ledger        4 row(s) recorded
```

That is an accurate description of the situation and of what is left: one physical action.
Nothing else fails.

## 3. Two checks that were silently always-passing, and how they were caught

This is the part worth reading, because the same mistake was made twice in one hour.

**The driver check.** First version compared the class GUID in lowercase against a registry
that writes it in lowercase - but the constant I typed contained an uppercase `D`
(`{4D36E978-...}`). Every row reported NO, including the two genuine `qcwdfser` sockets.
A check that always says NO would have sent the next attempt to "fix the driver" on a socket
that was already fine.

**The stale-holder check.** First version built a PowerShell command inline with escaped
quotes. PowerShell received a broken command line, every `CommandLine` came back empty, and
the result was a clean "none detected" - while nothing had been inspected at all. Fixed by
writing the query to a `.ps1` file (no escaping) and by making the function return `None`
for "could not look", which the caller reports as FAIL. **`[]` means measured-empty; `None`
means unknown.** Collapsing those two is exactly how an always-passing check is born.

The holder check was then given a **positive control**: a python process whose command line
contains `catch` was started, and the detector reported it:

```
detected: ['6576: "...\\python.exe" _fake_catcher.py']
```

Without that control, "none detected" on an idle machine would have been indistinguishable
from a broken query - which is precisely what the first version was.

## 4. Where this leaves the goal

`HELLO ver=3 mode=0`: **not obtained.**

The desk side is now closed and self-checking: the socket can be read, no process is
holding the port, the programmer is on disk, and the ledger will record what happens. The
one remaining precondition is the one no software can satisfy - the tablet has to be
power-cycled, and only a person in front of it can do that.

Next, in one line: `python scripts/preflight.py` then, if it is clean,
`python scripts/tablet.py catch --seconds 180`.
