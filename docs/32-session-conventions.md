# Session conventions (mandatory)

These are hard rules for anyone — human or agent — working in this repository.
They exist because both failures below cost real time and produced misleading
results, not merely inconvenience.

---

## 1. Never truncate a script's output

**Forbidden:**

```powershell
python script.py | Select-Object -First 40
python script.py 2>&1 | Select -First 30
python script.py | head -n 50
python script.py | tail -n 20
```

**Why this is not a style preference.** Piping into a truncating selector closes
the pipeline once enough lines are emitted. In PowerShell the upstream process
receives a broken stdout and dies mid-run. The consequences observed here:

- `catch_hello.py` was reported as "no bytes / failed" when the process had in
  fact been killed after 30 lines of output;
- long-running device tools (`QSaharaServer`, the Sahara clients) were terminated
  while they were still holding a COM port, which leaves the node mute until a
  power cycle and looks exactly like a device fault;
- the tail of a log is usually where the verdict is, and `-First` throws it away,
  so a run "fails" for a reason that was never displayed.

**Instead:** let the script finish, and control its size at the source — the
script already writes artefacts and a log file. Read the log file afterwards, or
use `Tee-Object` to keep everything and then read the part you need. If output
really must be filtered, filter the *file*, not the live pipe:

```powershell
python script.py *> run.log            # complete, on disk
Get-Content run.log -Tail 40           # inspect after the process exits
```

## 2. No long waits without a stated reason

Do not `Start-Sleep` for tens of seconds, and do not launch a task with a
multi-minute timeout, "to be safe".

A wait is only acceptable when a **specific measured event** is expected, and the
wait must be bounded by that event:

```python
# good: bounded by the thing being measured
while time.time() < deadline and not present(port):
    time.sleep(0.002)

# bad: a guess about how long a device takes
time.sleep(60)
```

If the expected event does not arrive, report it as a **negative result at once**
rather than sleeping longer. A measured "nothing happened in 3 s" is a finding;
a 60 s sleep that ends in the same statement is two wasted minutes.

Corollary for background work: poll for the *result* (process exited, file
written, port changed) with a short interval, and move on to other work in the
meantime instead of blocking on a timer.

## 3. Do not confuse an observer defect with a device finding

Two entries in this repository are already about that mistake
(`22-device-stopped-cycling.md`, `23-no-boot-loop.md`). The rule that follows:

> Before recording a device as broken, silent, or absent, prove the measuring
> tool is working — a control read, a known-good path, or the same operation
> through a second implementation.

This is exactly how the `timing_window.py` `errno 13` storm and the
`Select-Object -First` deaths were caught: by running the same thing a second way.

## 4. Report a negative result as a result

`docs/07-dead-ends.md` is the most valuable document in this repository because
every failed approach carries the reason it failed. Keep that standard: a
negative result with a stated cause is progress, and it must be written down
rather than retried.

---

## Where these rules came from

Both rules were adopted on 2026-11-11, at the owner's instruction, after a
session in which piped truncation killed device tools and long unconditional
sleeps produced no information. They apply to every script added to `scripts/`
and to every command run against the tablet.
