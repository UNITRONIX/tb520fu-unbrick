# The word "repeatable" needed a ledger, so here it is

The objective asks for *repeatable, documented* acquisition of `05C6:9008` with
`HELLO ver=3 mode=0`. This session found that the repository could not answer a simple
question about its own history: **how many attempts were made at method M, and how many
of them worked?** Everything was in prose, one narrative per session.

---

## 1. What was missing, stated precisely

`docs/07` lists 30+ failed attempts. `docs/23` says the bump "was verified twice".
`docs/97` records that the founding `HELLO ver=3 mode=0` has no raw capture. Put together:
the project has plenty of claims about success and no way to count them or check them.

That is a problem specific to this goal, because the goal is not "reach EDL once" - it is
`repeatable`. A single success does not satisfy it, and until now nothing in the tree could
distinguish one lucky run from a working method.

## 2. The ledger

`scripts/attempts.py` appends one JSON line per physical attempt:

```
when · route (catch|short|bump|manual) · keys (none|volup|voldown|both)
     · orientation (A|B for a D+ short) · outcome · hello_ver · hello_mode
     · capture (the .bin that proves it) · note
```

`--summary` groups by route and keys and prints the rate. It also refuses to call anything
repeatable on the strength of one row:

```
goal-state successes: 1
one success is NOT repeatability - repeat the same method and add a row
```

## 3. The rule that makes the ledger worth having

`--outcome success` is **downgraded to `9008-mute`** unless a capture exists *and* that
capture's sidecar says `is_goal_state: true`. Two downgrade paths, both tested
(`scripts/test_attempts.py`, all pass):

| situation | recorded as |
|---|---|
| success claimed, no capture at all | `9008-mute` |
| success claimed, capture says mode=2 | `9008-mute` |
| success claimed, capture says ver=3 mode=0 | `success` |

Without this the ledger is just another place to type "it worked", which is the failure
`docs/97` documented. With it, the ledger's success column *is* the evidence.

A second guard came out of writing the tests: the capture must be **recent** (default 5
minutes). Taking simply "the newest file" meant a success recorded after a failed attempt
would inherit the previous attempt's packet - the most important field on the row pointing
at the wrong event.

## 4. Filling it automatically

`tablet.py` now calls `log_attempt()` whenever it reads a HELLO - from `catch`, from
`grab_edl_hello`, from `grab_any_hello`. So the record happens whether or not anyone
remembers to write it, which is the only kind of documentation that survives a session like
this one.

## 5. The current contents, honestly

Four attempts from today are recorded, all with the observation behind them:

| route | keys | attempts | success |
|---|---|---|---|
| bump | none | 1 | 0 (`900E`, HELLO spent) |
| catch | none | 1 | 0 (wedge) |
| catch | volup | 1 | 0 (wedge) |
| manual | volup | 1 | 0 (wedge) |

**Zero goal-state successes.** The two synthetic rows written while testing the recorder
were deleted, because an evidence file containing invented entries is worse than an empty
one - the same principle as `hello_captures/README.md`.

## 6. Status

`HELLO ver=3 mode=0`: **not obtained.** The ledger says so in a form that can be counted,
and it will keep saying so until a run produces a capture that proves otherwise. The next
attempt - whichever route is chosen after power removal - will add its own row without
anyone having to remember.
